"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime

from homeassistant.util import dt as dt_util
import pytest

from custom_components.cainiao.const import ParcelStatus
from custom_components.cainiao.parcels import (
    normalize_parcel,
    parse_iso,
    planned_window,
)

from .payloads import (
    active_sample,
    delivered_sample,
    pickup_sample,
    real_active_sample,
    trace,
)

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

# 2099-03-04 12:00 UTC
_MOMENT_MS = 4_072_449_600_000


def _collected() -> dict:
    sample = pickup_sample()
    sample["latestTrace"] = trace("GTMS_SIGNED", 1_777_200_000_000, "Collected")
    sample["detailList"] = [
        sample["latestTrace"],
        trace("GTMS_STA_SIGNED", 1_777_150_000_000, "Arrived at pickup point"),
    ]
    return sample


def _moment_only() -> dict:
    sample = active_sample()
    sample["globalEtaInfo"] = {
        "deliveryMinTime": _MOMENT_MS,
        "deliveryMaxTime": _MOMENT_MS,
    }
    return sample


def _window() -> dict:
    sample = active_sample()
    sample["globalEtaInfo"] = {
        "deliveryMinTime": _MOMENT_MS,
        "deliveryMaxTime": _MOMENT_MS + 86_400_000 * 2,
    }
    return sample


def _ended_with_eta(code: str) -> dict:
    sample = active_sample()
    sample["latestTrace"] = trace(code, 1_777_150_000_000, "x")
    sample["globalEtaInfo"] = {
        "deliveryMinTime": _MOMENT_MS,
        "deliveryMaxTime": _MOMENT_MS + 3_600_000,
    }
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "at_pickup_point": pickup_sample,
    "collected": _collected,
    "problem": lambda: _ended_with_eta("EXCEPTION"),
    "pickup_with_eta": lambda: _ended_with_eta("GTMS_STA_SIGNED"),
    "delivered_with_eta": lambda: _ended_with_eta("GTMS_SIGNED"),
    "moment_only": _moment_only,
    "window": _window,
    "real_active": real_active_sample,
    "bare": lambda: {"mailNo": "LP00000000000"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_waiting_or_delivered_parcel_loses_its_eta():
    for code in ("GTMS_STA_SIGNED", "GTMS_SIGNED"):
        parcel = normalize_parcel(_ended_with_eta(code))
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None
    assert normalize_parcel(_ended_with_eta("EXCEPTION"))["planned_from"] is not None


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_collected())
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] is None


def test_a_home_delivery_is_not_pickup():
    assert normalize_parcel(delivered_sample())["pickup"] is False


def test_a_moment_ends_at_the_end_of_that_day():
    parcel = normalize_parcel(_moment_only())
    zone = dt_util.get_default_time_zone()
    end = datetime.fromisoformat(parcel["planned_to"])
    assert end.tzinfo is not None
    local = end.astimezone(zone)
    assert (local.hour, local.minute, local.second) == (23, 59, 59)
    assert local.date() == parse_iso(parcel["planned_from"]).astimezone(zone).date()


def test_a_window_keeps_both_ends():
    parcel = normalize_parcel(_window())
    assert parse_iso(parcel["planned_from"]) == datetime.fromtimestamp(
        _MOMENT_MS / 1000, tz=dt_util.UTC
    )
    assert parse_iso(parcel["planned_to"]) == datetime.fromtimestamp(
        (_MOMENT_MS + 86_400_000 * 2) / 1000, tz=dt_util.UTC
    )


def test_a_date_covers_the_whole_day():
    start, end = planned_window(
        "2099-03-04", None, zone=dt_util.get_default_time_zone()
    )
    first = datetime.fromisoformat(start)
    last = datetime.fromisoformat(end)
    assert (first.hour, first.minute, first.second) == (0, 0, 0)
    assert (last.hour, last.minute, last.second, last.microsecond) == (23, 59, 59, 0)
    assert first.date() == last.date()
