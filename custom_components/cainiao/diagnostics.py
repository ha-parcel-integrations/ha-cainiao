"""Diagnostics support for the Cainiao parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import CainiaoConfigEntry

# Diagnostics are pasted into public issues, so redact anything that identifies
# a person, an address or a specific parcel. Over-redacting is cheap;
# under-redacting leaks a user's home address into a GitHub thread.
#
# Cainiao's payload is anonymous by nature — it names neither sender nor
# receiver — so the tracking numbers are the sensitive part. Both of them: the
# Cainiao number *and* the local carrier's number it was handed off to, since
# either one is enough to look the parcel up on a public tracking page.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "url",
    # Cainiao payload fields
    "mailNo",
    "mailNoList",
    "copyRealMailNo",
    "realMailNo",
    # defensive: not seen on this endpoint, but cheap to guard against a
    # payload that starts carrying them
    "address",
    "postalCode",
    "city",
    "street",
    "email",
    "phone",
    "name",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CainiaoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Cainiao config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
