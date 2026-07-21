"""Tests for the Cainiao coordinator: fetching, caching and events.

The parcel mapping itself is covered by ``test_parcels.py``.
"""
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cainiao.api import CainiaoApiError
from custom_components.cainiao.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DOMAIN,
    REFRESH_INTERVAL_MINUTES,
    ParcelStatus,
)
from custom_components.cainiao.coordinator import CainiaoCoordinator

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    delivered_sample,
    trace,
)

OTHER_CODE = "LP00888888888"


def _entry_with(codes: list[str]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        # Keep-most-recent-100 so the delivered-retention filter never trims
        # the (old, fixed-date) sample parcels these tests assert on.
        options={
            CONF_PARCELS: [{CONF_TRACKING_CODE: code} for code in codes],
            CONF_DELIVERED_FILTER_TYPE: "parcels",
            CONF_DELIVERED_FILTER_AMOUNT: 100,
        },
        unique_id=DOMAIN,
    )


def _returning(*entries: dict) -> AsyncMock:
    client = AsyncMock()
    client.async_get_parcels.return_value = {
        entry["mailNo"]: entry for entry in entries
    }
    return client


def _in_transit(code: str = ACTIVE_CODE) -> dict:
    """A parcel that has not yet reached the local courier."""
    return active_sample(code)


def _out_for_delivery(code: str = ACTIVE_CODE) -> dict:
    sample = active_sample(code)
    sample["latestTrace"] = trace(
        "GTMS_DO_DEPART", 1_777_100_000_000, "Out for delivery"
    )
    return sample


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


def test_poll_cadence_is_the_fixed_six_hours(hass):
    """Cainiao's whole rate-limit strategy rests on this not being tunable."""
    entry = _entry_with([])
    entry.add_to_hass(hass)
    coordinator = CainiaoCoordinator(hass, AsyncMock(), entry)

    assert REFRESH_INTERVAL_MINUTES == 360
    assert coordinator.update_interval.total_seconds() == 6 * 3600


async def test_update_splits_active_and_delivered(hass):
    entry = _entry_with([ACTIVE_CODE, DELIVERED_CODE])
    entry.add_to_hass(hass)
    client = _returning(active_sample(), delivered_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()

    assert [parcel["barcode"] for parcel in data] == [ACTIVE_CODE]
    assert len(coordinator.delivered) == 1
    assert coordinator.last_success_time is not None


async def test_update_asks_for_every_code_in_one_call(hass):
    """One batched request, not one per parcel — see the module docstring."""
    entry = _entry_with([ACTIVE_CODE, DELIVERED_CODE])
    entry.add_to_hass(hass)
    client = _returning(active_sample(), delivered_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    await coordinator._async_update_data()

    client.async_get_parcels.assert_awaited_once_with([ACTIVE_CODE, DELIVERED_CODE])


async def test_unanswered_code_shows_a_pending_placeholder(hass):
    """A number Cainiao says nothing about must not make its sensor vanish."""
    entry = _entry_with([OTHER_CODE])
    entry.add_to_hass(hass)
    coordinator = CainiaoCoordinator(hass, _returning(), entry)

    data = await coordinator._async_update_data()

    assert len(data) == 1
    assert data[0]["barcode"] == OTHER_CODE
    assert data[0]["status"] == ParcelStatus.UNKNOWN


async def test_unanswered_code_falls_back_to_the_cached_payload(hass):
    entry = _entry_with([DELIVERED_CODE])
    entry.add_to_hass(hass)
    client = _returning(delivered_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)
    await coordinator._async_update_data()  # populates the cache

    client.async_get_parcels.return_value = {}
    await coordinator._async_update_data()

    assert len(coordinator.delivered) == 1


async def test_a_failed_request_fails_the_whole_poll(hass):
    """The batched call has no partial-success case: it works or it doesn't.

    The error propagates out of ``_async_update_data``; DataUpdateCoordinator
    turns it into ``UpdateFailed`` and backs off, and the last good data stays
    on the sensors meanwhile.
    """
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = AsyncMock()
    client.async_get_parcels.side_effect = CainiaoApiError("HTTP 503")
    coordinator = CainiaoCoordinator(hass, client, entry)

    with pytest.raises(CainiaoApiError):
        await coordinator._async_update_data()

    assert coordinator.last_success_time is None


async def test_update_skips_items_missing_a_tracking_code(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_PARCELS: [
                {CONF_TRACKING_CODE: ""},
                {CONF_TRACKING_CODE: DELIVERED_CODE},
            ]
        },
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    client = _returning(delivered_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    await coordinator._async_update_data()

    client.async_get_parcels.assert_awaited_once_with([DELIVERED_CODE])


async def test_update_backfills_a_missing_number(hass):
    """An edge payload without its own number keeps the code we asked for."""
    entry = _entry_with([OTHER_CODE])
    entry.add_to_hass(hass)
    sample = active_sample()
    del sample["mailNo"]
    client = AsyncMock()
    client.async_get_parcels.return_value = {OTHER_CODE: sample}
    coordinator = CainiaoCoordinator(hass, client, entry)

    data = await coordinator._async_update_data()
    assert data[0]["barcode"] == OTHER_CODE


async def test_update_prunes_cache_for_untracked_parcels(hass):
    entry = _entry_with([DELIVERED_CODE])
    entry.add_to_hass(hass)
    coordinator = CainiaoCoordinator(hass, _returning(delivered_sample()), entry)
    coordinator._raw_cache["GONE"] = {"mailNo": "GONE"}

    await coordinator._async_update_data()

    assert "GONE" not in coordinator._raw_cache
    assert DELIVERED_CODE in coordinator._raw_cache


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


async def test_first_refresh_fires_nothing(hass):
    """Otherwise every restart floods the user with "registered" events."""
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    coordinator = CainiaoCoordinator(hass, _returning(active_sample()), entry)

    fired = []
    for suffix in (
        "parcel_registered",
        "parcel_status_changed",
        "parcel_delivered",
        "parcel_delivery_time_changed",
    ):
        hass.bus.async_listen(f"{DOMAIN}_{suffix}", lambda e: fired.append(e))

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_event_carries_device_id(hass):
    from homeassistant.helpers import device_registry as dr

    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
    )
    client = _returning(_in_transit())
    coordinator = CainiaoCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e))

    await coordinator._async_update_data()
    client.async_get_parcels.return_value = {ACTIVE_CODE: _out_for_delivery()}
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events[0].data["device_id"] == device.id


async def test_fires_status_changed_event(hass):
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = _returning(_in_transit())
    coordinator = CainiaoCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", lambda e: events.append(e))

    await coordinator._async_update_data()  # first refresh: suppressed

    client.async_get_parcels.return_value = {ACTIVE_CODE: _out_for_delivery()}
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["old_status"] == ParcelStatus.IN_TRANSIT
    assert events[0].data["new_status"] == ParcelStatus.OUT_FOR_DELIVERY


async def test_delivery_fires_delivered_event_and_not_status_changed(hass):
    """The hop to delivered fires exactly one, dedicated event."""
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = _returning(active_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    delivered = []
    changed = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: delivered.append(e))
    hass.bus.async_listen(f"{DOMAIN}_parcel_status_changed", lambda e: changed.append(e))

    await coordinator._async_update_data()
    client.async_get_parcels.return_value = {
        ACTIVE_CODE: delivered_sample(ACTIVE_CODE)
    }
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert changed == []
    assert len(delivered) == 1
    assert delivered[0].data["status"] == ParcelStatus.DELIVERED


async def test_no_events_for_parcel_first_seen_delivered(hass):
    """A parcel already delivered when first tracked fires nothing at all."""
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = _returning(active_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    fired = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: fired.append(e))
    hass.bus.async_listen(f"{DOMAIN}_parcel_delivered", lambda e: fired.append(e))

    await coordinator._async_update_data()  # first refresh seeds the state

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: [
                {CONF_TRACKING_CODE: ACTIVE_CODE},
                {CONF_TRACKING_CODE: DELIVERED_CODE},
            ],
        },
    )
    client.async_get_parcels.return_value = {
        ACTIVE_CODE: active_sample(),
        DELIVERED_CODE: delivered_sample(),
    }
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert fired == []


async def test_fires_registered_event_for_new_parcel(hass):
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = _returning(active_sample())
    coordinator = CainiaoCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(f"{DOMAIN}_parcel_registered", lambda e: events.append(e))

    await coordinator._async_update_data()  # first refresh: suppressed

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PARCELS: [
                {CONF_TRACKING_CODE: ACTIVE_CODE},
                {CONF_TRACKING_CODE: OTHER_CODE},
            ],
        },
    )
    client.async_get_parcels.return_value = {
        ACTIVE_CODE: active_sample(),
        OTHER_CODE: active_sample(OTHER_CODE),
    }
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["barcode"] == OTHER_CODE


async def test_delivery_time_events_never_fire(hass):
    """Cainiao exposes no ETA, so this event has nothing to fire on.

    Kept as a test rather than deleted: if a future payload does carry a
    window, this failing is the signal to wire it up.
    """
    entry = _entry_with([ACTIVE_CODE])
    entry.add_to_hass(hass)
    client = _returning(_in_transit())
    coordinator = CainiaoCoordinator(hass, client, entry)

    events = []
    hass.bus.async_listen(
        f"{DOMAIN}_parcel_delivery_time_changed", lambda e: events.append(e)
    )

    await coordinator._async_update_data()
    client.async_get_parcels.return_value = {ACTIVE_CODE: active_sample()}
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []
