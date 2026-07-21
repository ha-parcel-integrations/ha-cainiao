"""Tests for Cainiao diagnostics."""
from unittest.mock import MagicMock

from custom_components.cainiao.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .payloads import DELIVERED_CODE, delivered_sample
from custom_components.cainiao.parcels import normalize_parcel


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — no tracking number may survive.

    Both numbers matter: the Cainiao one and the local carrier's handoff
    number, since either is enough to look the parcel up on a public page.
    """
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": DELIVERED_CODE}]}
    entry.runtime_data.coordinator.data = [normalize_parcel(delivered_sample())]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"

    parcel = result["incoming"][0]
    assert parcel["barcode"] == "**REDACTED**"
    assert parcel["url"] == "**REDACTED**"
    assert parcel["raw"]["mailNo"] == "**REDACTED**"
    assert parcel["raw"]["copyRealMailNo"] == "**REDACTED**"
    assert parcel["raw"]["realMailNo"] == "**REDACTED**"

    # Non-identifying fields survive, or the diagnostics would be useless.
    assert parcel["status"] == "delivered"
    assert parcel["raw"]["destCpInfo"]["cpName"] == "PostNL"
