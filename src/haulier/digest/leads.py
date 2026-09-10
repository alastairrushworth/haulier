"""Normalise extracted records into lead rows for the digest and CSV.

A record is what the extractor saw in one A&D entry; a lead is what a
subscriber receives (spec §4.2). The transforms here are deliberately shallow —
counts are parsed from authorisation strings, postcodes lifted from addresses —
because anything the source doesn't state stays empty rather than inferred.

Deltas: the source states the NEW authorisation ("New licence authorisation
will be 70 trailer(s)"), not the previous one, so `vehicles_delta` needs licence
history and stays empty until the pipeline has state (spec §4.2's "3 → 7" form).
The per-centre change text goes to the card and source_notes instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

#: Content-addressed event ids (PLAN.md §2.9): stable across re-runs.
EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://firstmover.example/events")

#: Heat order for digest sections (spec §4.1/§4.3).
HEAT_ORDER = [
    "NEW_APPLICATION",
    "VARIATION_APPLICATION",
    "APPLICATION_GRANTED",
    "VARIATION_GRANTED",
    "SURRENDER",
    "REVOCATION",
    "PUBLIC_INQUIRY",
    "APPLICATION_REFUSED",
    "APPLICATION_WITHDRAWN",
]

EVENT_LABELS = {
    "NEW_APPLICATION": "New application",
    "VARIATION_APPLICATION": "Variation application",
    "APPLICATION_GRANTED": "Application granted",
    "VARIATION_GRANTED": "Variation granted",
    "SURRENDER": "Licence surrendered",
    "REVOCATION": "Licence revoked",
    "PUBLIC_INQUIRY": "Public inquiry",
    "APPLICATION_REFUSED": "Application refused",
    "APPLICATION_WITHDRAWN": "Application withdrawn",
}

_VEHICLES_RE = re.compile(r"(\d+)\s+(?:Heavy goods |Light goods )?vehicle", re.IGNORECASE)
_TRAILERS_RE = re.compile(r"(\d+)\s+trailer", re.IGNORECASE)
_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b")

_CHANGE_LABELS = {
    "increase_at_existing": "increase at",
    "decrease_at_existing": "decrease at",
    "new_centre": "new centre",
    "removed_centre": "removed centre",
}

#: Tokens that settle an operator as a corporate body rather than an individual.
#: Only legal forms and public bodies — trade words like "TRANSPORT" or
#: "HAULAGE" appear in sole traders' trading names too, and guessing wrong in
#: this direction is the harmful one (spec §8.4: a sole trader routed to cold
#: email rather than phone or post).
_CORPORATE_TOKENS = frozenset(
    {
        "LTD",
        "LIMITED",
        "PLC",
        "LLP",
        "LP",
        "CIC",
        "CIO",
        "UNLIMITED",
        "INCORPORATED",
        "INC",
        "CORP",
        "CORPORATION",
        "COMPANY",
        "HOLDINGS",
        "GROUP",
        "COUNCIL",
        "BOROUGH",
        "UNIVERSITY",
        "COLLEGE",
        "ACADEMY",
        "SCHOOL",
        "NHS",
        "TRUST",
        "AUTHORITY",
        "ASSOCIATION",
        "SOCIETY",
        "FOUNDATION",
        "LLC",
        "GMBH",
        "BV",
        "SA",
    }
)

#: Trade words. A name carrying one is a business name, whoever holds it — a
#: sole trader may well trade as "SMITH HAULAGE" — so it settles nothing either
#: way and the entity type stays unknown rather than being guessed at. Without
#: this, "EASTERN PALLET NETWORK" is three plain words and reads as a person.
_TRADE_TOKENS = frozenset(
    {
        "TRANSPORT",
        "HAULAGE",
        "LOGISTICS",
        "DISTRIBUTION",
        "FREIGHT",
        "CARRIERS",
        "COURIERS",
        "COURIER",
        "REMOVALS",
        "SKIP",
        "SKIPS",
        "PLANT",
        "TIPPER",
        "TIPPERS",
        "CONTRACTORS",
        "CONTRACTING",
        "CONSTRUCTION",
        "ENGINEERING",
        "SERVICES",
        "SERVICE",
        "SUPPLIES",
        "TRADING",
        "FARM",
        "FARMS",
        "MOTORS",
        "GARAGE",
        "RECYCLING",
        "WASTE",
        "AGGREGATES",
        "BUILDERS",
        "NETWORK",
        "PALLET",
        "PALLETS",
        "EXPRESS",
        "CARGO",
        "SHIPPING",
        "STORAGE",
        "WAREHOUSING",
        "SOLUTIONS",
        "ENTERPRISES",
        "VEHICLE",
        "VEHICLES",
    }
)

#: "SMITH & PARTNERS", "THE X PARTNERSHIP": a partnership unless a legal form
#: says otherwise ("X PARTNERS LTD" is a company, an LLP is a body corporate).
#: ~130 operator lines in the 2026 corpus take the "& PARTNERS" shape, and the
#: extractor does not always give them a `people_role`.
_PARTNERSHIP_TOKENS = frozenset({"PARTNERS", "PARTNERSHIP"})

#: Two to five plain words — the shape of a person's name in this source.
_NAME_WORD = r"[A-Za-z][A-Za-z'\u2019.\-]*"
_PERSONAL_NAME_RE = re.compile(rf"^{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,4}}$")

_HONORIFICS = frozenset({"MR", "MRS", "MS", "MISS", "MX", "DR", "SIR", "DAME", "PROF"})

#: "JOHN SMITH T/A SMITH HAULAGE": the legal entity, then its trading name.
#: Seen 49 times across the 2026 corpus, mostly on companies — but when the
#: part before the marker is a bare personal name, the operator is a sole
#: trader and that name is personal data (spec §8.4, PLAN §2.11).
_TRADING_AS_RE = re.compile(r"\s+(?:T/A|T/AS|T\.A\.|TRADING\s+AS)\s+", re.IGNORECASE)


def legal_name(operator_name: str) -> str:
    """The entity before any trading-as marker; the whole name when there is none."""
    return _TRADING_AS_RE.split(operator_name, maxsplit=1)[0].strip()


def _looks_personal(name: str) -> bool:
    tokens = {token.strip(".,").upper() for token in name.split()}
    if tokens & (_CORPORATE_TOKENS | _TRADE_TOKENS) or "&" in name or "/" in name:
        return False
    return bool(_PERSONAL_NAME_RE.match(name.strip()))


def is_sole_trader_or_partnership(record: dict[str, Any]) -> bool | None:
    """Spec §4.2/§8.4 — True, False, or None when the source will not say.

    `people_role` is the strong signal: the source names *directors* for a
    company and *partners* for a partnership. Falling back to the operator
    name, a bare personal name is a sole trader and a legal-form or public-body
    token is not. Anything else stays None rather than being guessed at — an
    empty cell tells the subscriber to check, a wrong `no` does not.
    """
    role = (record.get("people_role") or "").strip().casefold()
    if role.startswith(("partner", "sole trader")):
        return True
    if role.startswith("director"):
        return False
    name = record.get("operator_name")
    if not name:
        return None
    # "C A D SERVICES LIMITED T/A FACILITIES BY ADF" is a company; "JOHN SMITH
    # T/A SMITH HAULAGE" is a sole trader. The part before the marker decides.
    entity = legal_name(name)
    tokens = {token.strip(".,").upper() for token in entity.split()}
    if tokens & _CORPORATE_TOKENS:
        return False
    if tokens & _PARTNERSHIP_TOKENS:
        return True
    return True if _looks_personal(entity) else None


def place_of(address: str | None) -> str | None:
    """'Norwich, NR9 5SG' — the part of an address the public sample may keep."""
    place = town_of(address)
    code = postcode_of(address)
    joined = ", ".join(part for part in (place, code) if part)
    return joined or None


def parse_counts(text: str | None) -> tuple[int | None, int | None]:
    """(vehicles, trailers) parsed from an authorisation phrase, summing
    HGV and LGV mentions. None when the phrase names no such count."""
    if not text:
        return None, None
    vehicles = [int(m) for m in _VEHICLES_RE.findall(text)]
    trailers = [int(m) for m in _TRAILERS_RE.findall(text)]
    return (sum(vehicles) if vehicles else None, sum(trailers) if trailers else None)


def postcode_of(address: str | None) -> str | None:
    if not address:
        return None
    matches = _POSTCODE_RE.findall(address.upper())
    return f"{matches[-1][0]} {matches[-1][1]}" if matches else None


def _titlecase(text: str) -> str:
    """Title-case that survives an apostrophe — `str.title()` gives "King'S Lynn"."""
    return re.sub(
        r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?",
        lambda m: m.group(0).capitalize(),
        text.casefold(),
    )


def town_of(address: str | None) -> str | None:
    """The last comma-separated component that is not the postcode.

    The postcode may be its own component or share one with the town
    ("… , NORWICH NR9 5SG"), so it is stripped either way.
    """
    if not address:
        return None
    parts = [" ".join(part.split()) for part in address.split(",") if part.strip()]
    parts = [part for part in parts if not _POSTCODE_RE.fullmatch(part.upper())]
    if not parts:
        return None
    town = _POSTCODE_RE.sub("", parts[-1].upper()).strip(" ,")
    return _titlecase(town) if town else None


@dataclass(frozen=True, slots=True)
class Lead:
    event_id: str
    event_type: str
    section: str
    event_date: str
    licence_number: str | None
    licence_type: str | None
    operator_name: str | None
    people_role: str | None
    people: list[str] = field(default_factory=list)
    correspondence_address: str | None = None
    operating_centres: list[dict[str, Any]] = field(default_factory=list)
    variation_centres: list[dict[str, Any]] = field(default_factory=list)
    """The centres a variation changes. The source states them here rather than
    in `operating_centres`, but they are operating centres all the same."""
    vehicles_authorised: int | None = None
    trailers_authorised: int | None = None
    change_summary: list[str] = field(default_factory=list)
    transport_managers: list[str] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    notes: str | None = None
    sole_trader_or_partnership: bool | None = None

    @property
    def label(self) -> str:
        return EVENT_LABELS.get(self.event_type, self.event_type)

    @property
    def personal_names(self) -> list[str]:
        """Every full personal name this lead carries — what the public sample
        must not show. Longest first, so an overlapping shorter name cannot
        pre-empt a longer one when scrubbing free text.

        The operator name counts when its legal entity is a bare personal name,
        whether or not it goes on to trade as something else: "JOHN SMITH T/A
        SMITH HAULAGE" names John Smith just as surely as "JOHN SMITH" does.
        """
        names = [n for n in (*self.people, *self.transport_managers) if n]
        if self.operator_name:
            entity = legal_name(self.operator_name)
            if _looks_personal(entity):
                names.append(entity)
        return sorted(set(names), key=lambda n: (-len(n), n))

    @property
    def first_centre_place(self) -> str | None:
        for centre in self.operating_centres:
            place = place_of(centre.get("address"))
            if place:
                return place
        return None

    @property
    def operating_centre_postcodes(self) -> list[str]:
        """Load-bearing for radius filtering (PLAN §2.12), so it gets its own
        CSV column rather than staying buried in the address blob.

        Varied centres count. On the pilot release, 51 of 131 leads state their
        only location in `variation_changes`, and every one of them is an
        expansion — the highest-value event type there is.
        """
        seen: list[str] = []
        for centre in (*self.operating_centres, *self.variation_centres):
            code = postcode_of(centre.get("address"))
            if code and code not in seen:
                seen.append(code)
        return seen

    @property
    def fleet_line(self) -> str | None:
        def plural(count: int, noun: str) -> str:
            return f"{count} {noun}{'s' if count != 1 else ''}"

        parts = []
        if self.vehicles_authorised is not None:
            parts.append(plural(self.vehicles_authorised, "vehicle"))
        if self.trailers_authorised is not None:
            parts.append(plural(self.trailers_authorised, "trailer"))
        return " / ".join(parts) if parts else None


def content_hash(record: dict[str, Any]) -> str:
    """SHA-256 over the record's canonical JSON — PLAN §2.9's `content_hash`.

    Hashing the whole record rather than a chosen subset of fields is what
    makes the id genuinely content-addressed. The earlier subset key
    (release|section|licence|event_type|operator|notes) collided on real data:
    East of England 5599 carries two DPDGROUP variations on OF0217601 that
    differ only in which operating centre changed, so the second — a
    50-vehicle expansion — hashed identically to the first. That is PLAN §2.2's
    legitimate-duplicate case, and it is a recall failure the recall metric
    cannot see, because the reconciliation counts licence numbers before
    anything downstream dedupes on the id.

    Key order is irrelevant (`sort_keys`), so re-runs are idempotent as long as
    the extractor is.
    """
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _change_summary(record: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for change in record.get("variation_changes") or []:
        label = _CHANGE_LABELS.get(change["kind"], change["kind"])
        place = town_of(change.get("address")) or ""
        code = postcode_of(change.get("address")) or ""
        where = ", ".join(p for p in (place, code) if p)
        auth = change.get("new_authorisation")
        lines.append(f"{label} {where}" + (f" → {auth}" if auth else ""))
    for total in record.get("new_licence_authorisation") or []:
        lines.append(f"new licence total: {total}")
    return lines


def build_lead(record: dict[str, Any], release: dict[str, Any]) -> Lead:
    centres = record.get("operating_centres") or []
    vehicles = trailers = None
    if record.get("event_type") in {"NEW_APPLICATION", "APPLICATION_GRANTED"} or centres:
        totals = [parse_counts(c.get("authorisation")) for c in centres]
        vehicle_counts = [v for v, _ in totals if v is not None]
        trailer_counts = [t for _, t in totals if t is not None]
        vehicles = sum(vehicle_counts) if vehicle_counts else None
        trailers = sum(trailer_counts) if trailer_counts else None
    else:
        # Variations: the new licence totals, when the source states them.
        joined = " ".join(record.get("new_licence_authorisation") or [])
        vehicles, trailers = parse_counts(joined)

    content_key = "|".join(
        [
            release["release_no"],
            record.get("licence_number") or "",
            record.get("event_type") or "",
            content_hash(record),
        ]
    )
    return Lead(
        event_id=str(uuid.uuid5(EVENT_NAMESPACE, content_key)),
        event_type=record["event_type"],
        section=record["section"],
        event_date=record.get("effective_date") or release["published_on"],
        licence_number=record.get("licence_number"),
        licence_type=record.get("licence_type"),
        operator_name=record.get("operator_name"),
        people_role=record.get("people_role"),
        people=record.get("people") or [],
        correspondence_address=record.get("correspondence_address"),
        operating_centres=centres,
        variation_centres=record.get("variation_changes") or [],
        vehicles_authorised=vehicles,
        trailers_authorised=trailers,
        change_summary=_change_summary(record),
        transport_managers=record.get("transport_managers") or [],
        considerations=record.get("considerations") or [],
        notes=record.get("notes"),
        sole_trader_or_partnership=is_sole_trader_or_partnership(record),
    )


def redact_name(name: str) -> str:
    """'JOHN ANDREW KILLETT' → 'J. A. K.' for the public sample (PLAN §2.11).

    Honorifics are dropped rather than initialised, so 'Mr CHRISTOPHER
    DARBYSHIRE' reads 'C. D.' and not 'M. C. D.'.
    """
    parts = [part for part in re.split(r"[\s-]+", name) if part and part[0].isalpha()]
    parts = [part for part in parts if part.strip(".").upper() not in _HONORIFICS] or parts
    initials = [part[0].upper() for part in parts]
    return " ".join(f"{i}." for i in initials) if initials else name


#: Structural words in an operator name that identify nobody, so they survive
#: redaction and keep "W. & Partners" readable as a partnership, and
#: "J. S. T/A S. Haulage" readable as a sole trader with a trading name.
_ENTITY_WORDS = frozenset(
    {"AND", "PARTNERS", "PARTNER", "PARTNERSHIP", "SONS", "SON", "T/A", "T/AS", "T.A.", "AS"}
)


def redact_operator_name(name: str) -> str:
    """'WYNDHAM & PARTNERS' → 'W. & Partners'; 'BARRY PINCHING' → 'B. P.'.

    A partnership's operator name need not contain any partner's full name —
    "Wyndham & Partners" for Cecily and Aubrey Wyndham — so substituting the
    known people out of it is not enough. Every personal token is initialised
    and only the structural words are kept. Honorifics are dropped, as in
    `redact_name`, so "MR BARRY PINCHING" is "B. P." and not "M. B. P.".
    """
    out: list[str] = []
    for token in re.split(r"(\s+|&)", name):
        bare = token.strip(".,()").upper()
        if not token.strip() or token == "&" or not token[0].isalpha():
            out.append(token)
        elif bare in _HONORIFICS:
            continue
        elif bare in _ENTITY_WORDS or bare in _CORPORATE_TOKENS or bare in _TRADE_TOKENS:
            out.append(token.capitalize() if token.isupper() and "/" not in token else token)
        else:
            out.append(f"{token[0].upper()}.")
    return " ".join("".join(out).split())


def _scrub(text: str | None, names: list[str]) -> str | None:
    """Replace each known personal name in free text with its initials."""
    if not text:
        return text
    for name in names:
        text = re.sub(re.escape(name), redact_name(name), text, flags=re.IGNORECASE)
    return text


def redact_lead(lead: Lead) -> Lead:
    """Everything the public sample must not carry (PLAN §2.11).

    Redacting the `people` and `transport_managers` lists alone leaves three
    open channels, all of which are populated in East of England 5599:

      1. `notes` — a transport-manager public inquiry names the individual in
         its free text ("... for GEORGE THOMAS to be held at ...").
      2. `operator_name` — a sole trader's or partnership's operator name *is*
         a personal name.
      3. `correspondence_address` and operating-centre addresses — for a sole
         trader these are, very often, a home address.

    Names known for the lead are scrubbed out of every free-text field, and a
    non-corporate operator's addresses are reduced to town and postcode, which
    is all the sample needs to make its point.
    """
    from dataclasses import replace

    names = lead.personal_names

    # A registered company name is a public business name, not personal data —
    # only a sole trader's or partnership's operator name gets initialised, so
    # "Patrick B Doyle (Construction) Limited" survives intact. The second test
    # is the safety net: whatever the entity flag says, an operator name whose
    # legal entity reads as a person is a person.
    operator_name = lead.operator_name
    if operator_name and (
        lead.sole_trader_or_partnership or _looks_personal(legal_name(operator_name))
    ):
        operator_name = redact_operator_name(operator_name)

    def scrub_addresses(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**entry, "address": place_of(entry.get("address"))} for entry in entries]

    reduce_addresses = lead.sole_trader_or_partnership is not False
    return replace(
        lead,
        operator_name=operator_name,
        people=[redact_name(n) for n in lead.people],
        transport_managers=[redact_name(n) for n in lead.transport_managers],
        notes=_scrub(lead.notes, names),
        considerations=[c for c in (_scrub(c, names) for c in lead.considerations) if c],
        change_summary=[c for c in (_scrub(c, names) for c in lead.change_summary) if c],
        correspondence_address=(
            place_of(lead.correspondence_address)
            if reduce_addresses
            else _scrub(lead.correspondence_address, names)
        ),
        operating_centres=(
            scrub_addresses(lead.operating_centres) if reduce_addresses else lead.operating_centres
        ),
        variation_centres=(
            scrub_addresses(lead.variation_centres) if reduce_addresses else lead.variation_centres
        ),
    )
