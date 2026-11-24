"""Tests for the contents action, the track_parcel field and the store lifecycle."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cainiao.const import CONF_PARCELS, CONF_TRACKING_CODE, DOMAIN
from custom_components.cainiao.contents import CONTENTS_STORE_MAX_CODES

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    as_map,
    delivered_sample,
)

FETCH = "custom_components.cainiao.api.CainiaoApiClient.async_get_parcels"
UNTRACKED = "EXAMPLE555555"
STORE_KEY = f"{DOMAIN}.contents.%s"


def _sample(codes):
    return as_map(*(active_sample(code) for code in codes))


def _config_entry(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, unique_id=DOMAIN, options={CONF_PARCELS: parcels}
    )


async def _setup(hass, codes: list[str] | None = None) -> MockConfigEntry:
    entry = _config_entry([{CONF_TRACKING_CODE: code} for code in codes or []])
    entry.add_to_hass(hass)
    with patch(FETCH, new=AsyncMock(return_value=_sample(codes or []))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _call(hass, service: str, data: dict) -> None:
    with patch(FETCH, new=AsyncMock(side_effect=lambda c: _sample(c))):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
        await hass.async_block_till_done()


COORDINATOR = "custom_components.cainiao.coordinator.CainiaoCoordinator"


def _contents(entry: MockConfigEntry, code: str) -> str | None:
    parcels = {p["barcode"]: p for p in entry.runtime_data.coordinator.data}
    return parcels[code]["contents"]


async def test_a_parcel_has_no_contents_without_a_stored_value(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_sets_replaces_and_clears(hass):
    entry = await _setup(hass, [ACTIVE_CODE])

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": " Running  shoes "},
    )
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Winter socks"},
    )
    assert _contents(entry, ACTIVE_CODE) == "Winter socks"

    await _call(
        hass, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "  "}
    )
    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_without_text_clears(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert _contents(entry, ACTIVE_CODE) is None


async def test_update_contents_normalizes_the_code(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: "lp-00999 999999", "contents": "Running shoes"},
    )
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def test_update_contents_works_for_a_code_that_is_not_tracked(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: UNTRACKED, "contents": "Running shoes"},
    )

    assert entry.runtime_data.coordinator.contents_store.get(UNTRACKED) == (
        "Running shoes"
    )
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]


async def test_update_contents_requests_nothing_from_the_carrier(hass):
    await _setup(hass, [ACTIVE_CODE])
    data = {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"}
    with (
        patch(FETCH, new=AsyncMock()) as fetch,
        patch(f"{COORDINATOR}.async_request_refresh", new=AsyncMock()) as refresh,
    ):
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        await hass.services.async_call(
            DOMAIN,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Winter socks"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN, "update_contents", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True
        )
        await hass.async_block_till_done()
    assert fetch.await_count == 0
    assert refresh.await_count == 0


async def test_update_contents_republishes_only_when_something_changed(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    data = {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"}
    with patch.object(
        coordinator, "republish_from_cache", wraps=coordinator.republish_from_cache
    ) as republish:
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        await hass.services.async_call(DOMAIN, "update_contents", data, blocking=True)
        await hass.services.async_call(
            DOMAIN, "update_contents", {CONF_TRACKING_CODE: UNTRACKED}, blocking=True
        )
    assert republish.call_count == 1


async def test_republish_keeps_the_cached_parcel_and_notifies_listeners(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    before = coordinator.last_success_time
    updates = []
    coordinator.async_add_listener(lambda: updates.append(1))

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert updates
    assert coordinator.last_success_time == before
    assert coordinator.data[0]["raw_status"] == active_sample()["statusDesc"]


async def test_republish_with_nothing_cached_still_lists_the_code(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    coordinator = entry.runtime_data.coordinator
    coordinator._raw_cache.clear()
    coordinator.republish_from_cache()
    assert [p["barcode"] for p in coordinator.data] == [ACTIVE_CODE]


async def test_a_delivered_parcel_keeps_its_contents(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={
            CONF_PARCELS: [{CONF_TRACKING_CODE: DELIVERED_CODE}],
            "delivered_filter_type": "parcels",
            "delivered_filter_amount": 5,
        },
    )
    entry.add_to_hass(hass)
    with patch(FETCH, new=AsyncMock(return_value=as_map(delivered_sample()))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: DELIVERED_CODE, "contents": "Running shoes"},
    )
    assert coordinator.delivered[0]["contents"] == "Running shoes"


async def test_update_contents_rejects_an_empty_code(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "update_contents", {CONF_TRACKING_CODE: ""})


async def test_update_contents_needs_a_loaded_entry(hass):
    entry = await _setup(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "update_contents",
            {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
        )
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_track_parcel_stores_contents_for_a_new_code(hass):
    entry = await _setup(hass)
    await _call(
        hass,
        "track_parcel",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def test_track_parcel_without_contents_is_unchanged(hass):
    entry = await _setup(hass)
    await _call(hass, "track_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert entry.runtime_data.coordinator.contents_store.get(ACTIVE_CODE) is None
    assert _contents(entry, ACTIVE_CODE) is None


async def test_track_parcel_replaces_and_clears_contents_of_a_tracked_code(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    track = {CONF_TRACKING_CODE: ACTIVE_CODE}

    await _call(hass, "track_parcel", {**track, "contents": "Running shoes"})
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"

    await _call(hass, "track_parcel", {**track, "contents": "Winter socks"})
    assert _contents(entry, ACTIVE_CODE) == "Winter socks"

    await _call(hass, "track_parcel", {**track, "contents": ""})
    assert _contents(entry, ACTIVE_CODE) is None
    assert entry.options[CONF_PARCELS] == [{CONF_TRACKING_CODE: ACTIVE_CODE}]


async def test_track_parcel_contents_change_requests_nothing_from_the_carrier(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    track = {CONF_TRACKING_CODE: ACTIVE_CODE}
    with (
        patch(FETCH, new=AsyncMock()) as fetch,
        patch(f"{COORDINATOR}.async_request_refresh", new=AsyncMock()) as refresh,
    ):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {**track, "contents": "Running shoes"},
            blocking=True,
        )
        await hass.async_block_till_done()
    assert _contents(entry, ACTIVE_CODE) == "Running shoes"
    assert fetch.await_count == 0
    assert refresh.await_count == 0


async def test_track_parcel_unchanged_contents_requests_no_refresh(hass):
    await _setup(hass, [ACTIVE_CODE])
    data = {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"}
    with (
        patch(FETCH, new=AsyncMock()) as fetch,
        patch(f"{COORDINATOR}.async_request_refresh", new=AsyncMock()) as refresh,
    ):
        await hass.services.async_call(DOMAIN, "track_parcel", data, blocking=True)
        await hass.services.async_call(DOMAIN, "track_parcel", data, blocking=True)
        await hass.async_block_till_done()
    assert fetch.await_count == 0
    assert refresh.await_count == 0


async def test_the_store_keeps_at_most_200_codes_and_drops_the_oldest(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    store = entry.runtime_data.coordinator.contents_store
    for number in range(CONTENTS_STORE_MAX_CODES):
        store.async_set(f"CODE{number}", "Item")
    assert store.get("CODE0") == "Item"
    store.async_set("CODE200", "Item")
    assert store.get("CODE0") is None
    assert store.get("CODE200") == "Item"
    assert store.get("CODE1") == "Item"


async def test_an_entry_without_a_store_file_works(hass, hass_storage):
    entry = await _setup(hass, [ACTIVE_CODE])
    assert STORE_KEY % entry.entry_id not in hass_storage
    assert _contents(entry, ACTIVE_CODE) is None


async def test_untrack_parcel_drops_the_contents(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE})

    assert entry.runtime_data.coordinator.contents_store.get(ACTIVE_CODE) is None
    assert entry.options[CONF_PARCELS] == []


async def test_a_stored_value_survives_a_restart_of_the_entry(hass, hass_storage):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )
    await entry.runtime_data.coordinator.contents_store._store.async_save(
        entry.runtime_data.coordinator.contents_store._data_to_save()
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    with patch(FETCH, new=AsyncMock(return_value=_sample([ACTIVE_CODE]))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert _contents(entry, ACTIVE_CODE) == "Running shoes"


async def test_removing_the_entry_removes_its_store(hass, hass_storage):
    entry = await _setup(hass, [ACTIVE_CODE])
    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )
    store = entry.runtime_data.coordinator.contents_store
    await store._store.async_save(store._data_to_save())
    key = STORE_KEY % entry.entry_id
    assert key in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


async def test_a_contents_change_alone_fires_no_event(hass):
    await _setup(hass, [ACTIVE_CODE])
    events = []
    for name in ("status_changed", "registered", "delivered", "delivery_time_changed"):
        hass.bus.async_listen(f"{DOMAIN}_parcel_{name}", events.append)

    await _call(
        hass,
        "update_contents",
        {CONF_TRACKING_CODE: ACTIVE_CODE, "contents": "Running shoes"},
    )

    assert events == []


async def test_untrack_works_while_the_entry_is_not_loaded(hass):
    entry = await _setup(hass, [ACTIVE_CODE])
    entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    with patch.object(hass.config_entries, "async_update_entry") as update:
        await hass.services.async_call(
            DOMAIN, "untrack_parcel", {CONF_TRACKING_CODE: ACTIVE_CODE}, blocking=True
        )
    assert update.call_count == 1
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert await hass.config_entries.async_unload(entry.entry_id)
