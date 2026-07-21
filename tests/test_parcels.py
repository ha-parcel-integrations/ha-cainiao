"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the Cainiao-specific mapping can be tested as
plain functions.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cainiao.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    ParcelStatus,
)
from custom_components.cainiao.parcels import (
    apply_delivered_filter,
    build_history,
    handoff_number,
    map_event_status,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    sort_parcels_by_ts,
    to_iso_timestamp,
)

from .payloads import (
    DELIVERED_CODE,
    UNKNOWN_MODULE_ENTRY,
    active_sample,
    delivered_sample,
    pickup_sample,
    trace,
)

# ---------------------------------------------------------------------------
# status mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_code,expected",
    [
        ("GWMS_ACCEPT", ParcelStatus.REGISTERED),
        ("LH_DEPART", ParcelStatus.IN_TRANSIT),
        ("CC_IM_START", ParcelStatus.IN_TRANSIT),
        ("GTMS_ACCEPT", ParcelStatus.IN_TRANSIT),
        ("GTMS_DO_DEPART", ParcelStatus.OUT_FOR_DELIVERY),
        ("GTMS_WAIT_SELF_PICK", ParcelStatus.AT_PICKUP_POINT),
        ("GTMS_SIGNED", ParcelStatus.DELIVERED),
        ("GTMS_STA_SIGN_FAILURE", ParcelStatus.PROBLEM),
        ("EXCEPTION", ParcelStatus.PROBLEM),
    ],
)
def test_map_event_status_known(action_code, expected):
    assert map_event_status(action_code) == expected


def test_station_signature_is_not_a_delivery():
    """GTMS_STA_SIGNED is the pickup point signing, not the recipient.

    Mapping it to DELIVERED would fire the delivered event while the parcel is
    still sitting in a locker.
    """
    assert map_event_status("GTMS_STA_SIGNED") == ParcelStatus.AT_PICKUP_POINT
    assert map_event_status("GTMS_SIGNED") == ParcelStatus.DELIVERED


def test_map_event_status_is_case_insensitive():
    assert map_event_status("gtms_signed") == ParcelStatus.DELIVERED
    assert map_event_status(" GTMS_SIGNED ") == ParcelStatus.DELIVERED


def test_map_event_status_missing_and_unmapped_are_none():
    """History keeps ``null`` rather than ``unknown`` so consumers can tell
    "no mapping" from "mapped to unknown"."""
    assert map_event_status(None) is None
    assert map_event_status("GOT_SCANNED_SOMEWHERE") is None


def test_parcel_status_comes_from_the_latest_trace():
    assert map_parcel_status(delivered_sample()) == ParcelStatus.DELIVERED
    assert map_parcel_status(active_sample()) == ParcelStatus.IN_TRANSIT
    assert map_parcel_status(pickup_sample()) == ParcelStatus.AT_PICKUP_POINT


def test_parcel_status_falls_back_to_the_newest_event():
    """Some payloads omit latestTrace; the timeline still describes the parcel."""
    raw = delivered_sample()
    del raw["latestTrace"]
    assert map_parcel_status(raw) == ParcelStatus.DELIVERED


def test_parcel_without_events_is_unknown_and_silent(caplog):
    """A not-yet-scanned parcel is the normal state for days — never warn."""
    assert map_parcel_status(UNKNOWN_MODULE_ENTRY) == ParcelStatus.UNKNOWN
    assert map_parcel_status({}) == ParcelStatus.UNKNOWN
    assert caplog.text == ""


def test_unmapped_action_warns_only_once(caplog):
    assert map_event_status("ABDUCTED_BY_ALIENS") is None
    assert map_event_status("ABDUCTED_BY_ALIENS") is None
    assert caplog.text.count("ABDUCTED_BY_ALIENS") == 1
    assert "issues/new" in caplog.text


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_converts_cainiao_epoch_milliseconds():
    assert to_iso_timestamp(1_777_200_000_000) == "2026-04-26T10:40:00+00:00"
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**20) is None  # out of range -> None, never raises


# ---------------------------------------------------------------------------
# handoff number — what a future aggregator dedupe would key on
# ---------------------------------------------------------------------------


def test_handoff_number_prefers_the_clean_field():
    assert handoff_number(delivered_sample()) == "3SDFC0123456789"


def test_handoff_number_extracts_from_the_display_string():
    raw = delivered_sample()
    del raw["copyRealMailNo"]
    assert handoff_number(raw) == "3SDFC0123456789"


def test_handoff_number_is_none_when_absent():
    assert handoff_number(UNKNOWN_MODULE_ENTRY) is None
    assert handoff_number({"realMailNo": "handed over locally"}) is None


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def test_build_history_orders_oldest_to_newest():
    history = build_history(delivered_sample()["detailList"])
    assert len(history) == 4
    assert history[0]["raw_status"] == "Departed from origin country"
    assert history[-1]["status"] == ParcelStatus.DELIVERED


def test_build_history_caps_to_max_events():
    events = [trace("LH_DEPART", 1_770_000_000_000 + n, "moved") for n in range(25)]
    assert len(build_history(events, max_events=20)) == 20


def test_build_history_handles_missing_and_malformed():
    assert build_history(None) == []
    assert build_history([{"actionCode": "LH_DEPART"}]) == []  # no timestamp
    assert build_history(["not-a-dict"]) == []


def test_build_history_falls_back_to_the_action_code():
    events = [{"actionCode": "GTMS_SIGNED", "time": 1_777_200_000_000}]
    assert build_history(events)[0]["raw_status"] == "GTMS_SIGNED"


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_normalize_delivered_parcel():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["carrier"] == "Cainiao"
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "Delivered"
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-04-26T10:40:00+00:00"
    assert parcel["url"].endswith(DELIVERED_CODE)
    assert parcel["history"] is None  # opt-in, default off


def test_normalize_active_parcel():
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_normalize_leaves_last_leg_fields_empty():
    """Cainiao exposes none of these; the local carrier's integration does."""
    parcel = normalize_parcel(active_sample())
    for key in (
        "sender",
        "receiver",
        "planned_from",
        "planned_to",
        "pickup_point",
        "weight",
        "dimensions",
    ):
        assert parcel[key] is None, key
    assert parcel["pickup"] is False


def test_normalize_history_is_opt_in():
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    assert len(parcel["history"]) == 4
    assert parcel["history"][-1]["status"] == ParcelStatus.DELIVERED


def test_normalize_unscanned_parcel_is_unknown_not_broken():
    """The state a cross-border parcel sits in for days after ordering."""
    parcel = normalize_parcel(UNKNOWN_MODULE_ENTRY)
    assert parcel["barcode"] == "LP00000000000"
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None


def test_normalize_falls_back_to_the_latest_trace_text():
    raw = active_sample()
    del raw["statusDesc"]
    assert normalize_parcel(raw)["raw_status"] == "Departed from origin country"


def test_normalize_pickup_parcel_is_not_delivered():
    parcel = normalize_parcel(pickup_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_normalize_keeps_raw_payload():
    raw = active_sample()
    assert normalize_parcel(raw)["raw"] is raw


# ---------------------------------------------------------------------------
# sorting and the delivered filter
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
