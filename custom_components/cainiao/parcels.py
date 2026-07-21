"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

The Cainiao-specific parts are :data:`_STATUS_MAP`, :func:`build_history`,
:func:`handoff_number` and :func:`normalize_parcel`. Everything else — the
timestamp parsing, the sort contract, the delivered filter, the one-shot
warning for unmapped statuses — is suite-wide machinery, kept identical across
carriers on purpose.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
NEW_ISSUE_URL = "https://github.com/ha-parcel-integrations/ha-cainiao/issues/new"

# Cainiao's ``status`` token → canonical ParcelStatus.
#
# The token is a stable, language-independent English string that sits next to
# the localised ``statusDesc``; mapping on the token rather than on prose is
# what keeps this from breaking when a user's ``lang`` changes.
#
# **The entries below are unverified.** They were not read off a live parcel —
# the vocabulary is inferred, and only ``delivered`` is known for certain. That
# is deliberate rather than sloppy: an unmapped token surfaces as ``unknown``
# plus a one-shot warning asking the user to report it, so the map grows from
# real payloads instead of from guesses. Adding a *wrong* mapping is worse than
# adding none, so when in doubt, leave it out.
#
# Comparison is case-insensitive (see :func:`_normalise_token`), because it is
# not established whether Cainiao reports these upper- or lower-case.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "delivered": ParcelStatus.DELIVERED,
    "signin": ParcelStatus.DELIVERED,
    "departure": ParcelStatus.IN_TRANSIT,
    "transport": ParcelStatus.IN_TRANSIT,
    "arrival": ParcelStatus.IN_TRANSIT,
    "customs": ParcelStatus.IN_TRANSIT,
    "delivering": ParcelStatus.OUT_FOR_DELIVERY,
    "pickup": ParcelStatus.AT_PICKUP_POINT,
    "return": ParcelStatus.RETURNING,
    "exception": ParcelStatus.PROBLEM,
}

# A tracking number embedded in Cainiao's ``realMailNo`` display string, which
# reads like "PostNL 3SDFC0123456789". Match a whole upper-case alphanumeric
# token of 8-30 characters that contains at least one digit — the digit
# requirement is what skips the carrier name sitting next to it.
_EMBEDDED_NUMBER_RE = re.compile(
    r"(?<![A-Z0-9])(?=[A-Z0-9]*[0-9])[A-Z0-9]{8,30}(?![A-Z0-9])"
)

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Cainiao status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def _normalise_token(code: str) -> str:
    """Lower-case a status token for lookup.

    Cainiao's casing is not established, so the map is matched case-insensitively
    rather than betting on one form and silently reporting ``unknown`` for the
    other.
    """
    return code.strip().lower()


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a Cainiao ``status`` token to a canonical :class:`ParcelStatus`.

    ``None`` — which is what a not-yet-scanned cross-border parcel gets, often
    for days after ordering — reports ``unknown`` silently. An unrecognised
    token reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(_normalise_token(code))
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a history entry's action code to a canonical status, or ``None``.

    Unmapped codes keep ``status: null`` on the history entry (rather than
    ``unknown``, so a consumer can tell "no mapping" from "mapped to unknown")
    and warn once, reusing the parcel-status one-shot set. Cainiao's per-event
    vocabulary is richer than the parcel-level one, so this warning is the main
    way the map will grow once real parcels flow through.
    """
    if not code:
        return None
    mapped = _STATUS_MAP.get(_normalise_token(code))
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the carrier's event list.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own text, or
    its event code when the API has no human-readable text. Sorted oldest →
    newest and capped to the most recent ``max_events``.

    Cainiao ships the whole timeline as ``detailList`` in the same response, so
    enabling history costs no extra request. Each entry carries ``time`` (epoch
    milliseconds), a human-readable ``desc``/``standerdDesc`` — that spelling is
    Cainiao's, not a typo here — and an ``actionCode`` we map where we can.
    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("time") or event.get("timeStr"))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": map_event_status(event.get("actionCode")),
            "raw_status": (
                event.get("standerdDesc")
                or event.get("desc")
                or event.get("actionCode")
            ),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def handoff_number(raw: dict) -> str | None:
    """Return the local carrier's own tracking number, if Cainiao knows it.

    A cross-border parcel is handed to a national carrier for the last leg, and
    Cainiao exposes that carrier's number. Kept under ``raw`` rather than
    promoted to a top-level canonical key: the same physical parcel can then
    show up twice in the aggregator — once as Cainiao, once as the local carrier
    — and this number is what a future deduplication would key on. Promoting it
    is a suite-wide contract change, not a Cainiao decision.

    ``copyRealMailNo`` is the clean value when present; ``realMailNo`` is a
    display string with the number embedded in it, alongside the carrier name.
    """
    clean = raw.get("copyRealMailNo")
    if isinstance(clean, str) and clean.strip():
        return clean.strip()

    display = raw.get("realMailNo")
    if isinstance(display, str):
        match = _EMBEDDED_NUMBER_RE.search(display)
        if match:
            return match.group(0)
    return None


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key Cainiao does not expose is
    ``None`` — never omitted.

    What Cainiao does not give us, and why the ``None``s are intentional:

    * **``sender`` / ``receiver``** — the endpoint is anonymous, keyed on the
      number alone, so it names neither party. ``destCpInfo.cpName`` is the
      *handoff carrier*, not the sender, and lives under ``raw``.
    * **``planned_from`` / ``planned_to``** — no delivery window is exposed for
      the cross-border leg. Once a parcel is handed to a local carrier, that
      carrier's own integration is where an ETA appears.
    * **``pickup`` / ``pickup_point``** — likewise a last-leg concept.
    * **``weight`` / ``dimensions``** — never exposed on consumer tracking.

    ``delivered_at`` comes from the latest trace's timestamp, which is the
    delivery scan once the parcel is delivered.
    """
    tracking_code = raw.get("mailNo")
    status_token = raw.get("status")
    status = map_parcel_status(status_token)
    delivered = status is ParcelStatus.DELIVERED

    latest_trace = raw.get("latestTrace") or {}

    return {
        "carrier": "Cainiao",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": raw.get("statusDesc")
        or latest_trace.get("standerdDesc")
        or status_token,
        "delivered": delivered,
        "delivered_at": (
            to_iso_timestamp(latest_trace.get("time")) if delivered else None
        ),
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "url": tracking_url(tracking_code),
        "weight": None,
        "dimensions": None,
        "history": build_history(raw.get("detailList")) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
