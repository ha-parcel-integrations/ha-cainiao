"""Coordinator for the Cainiao parcel tracker integration.

Fetching and event firing only — the parcel mapping lives in :mod:`.parcels`.

Cainiao is polled **in one batched request for every tracked number**, unlike
the other carriers in the suite which fetch one parcel at a time. That, plus the
fixed six-hour cadence, is the whole rate-limit strategy: Alibaba throttles
traffic it considers unusual, and a fan-out of parallel requests every half hour
is exactly that.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import CainiaoApiClient
from .const import (
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_TRACKING_CODE,
    DEFAULT_INCLUDE_HISTORY,
    DOMAIN,
    REFRESH_INTERVAL_MINUTES,
    ParcelStatus,
)
from .parcels import apply_delivered_filter, normalize_parcel, sort_parcels_by_ts

_LOGGER = logging.getLogger(__name__)


def _refresh_interval(entry: ConfigEntry) -> timedelta:
    """Return the fixed refresh interval as a ``timedelta``.

    Not user-configurable on purpose: this carrier throttles or soft-bans
    unusual traffic, so letting users dial the cadence down would get them
    blocked. Same signature as the configurable variant, so nothing else in
    the integration cares which one is compiled in.
    """
    return timedelta(minutes=REFRESH_INTERVAL_MINUTES)


class CainiaoCoordinator(DataUpdateCoordinator[list[dict]]):
    """Polls every tracked parcel in one request and publishes the parcel lists.

    Cainiao has no account or parcel feed, so the tracked parcels are the
    tracking numbers the user entered (stored in the entry options).
    ``coordinator.data`` is the active (not-yet-delivered) parcels,
    ``self.delivered`` the rest.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: CainiaoApiClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Passing config_entry makes self.config_entry available on the
            # base class, which every helper below relies on.
            config_entry=entry,
            name=DOMAIN,
            update_interval=_refresh_interval(entry),
        )
        self._client = client
        self.delivered: list[dict] = []
        # tracking_code -> last successful raw payload, so a transient fetch
        # failure or a not-found blip keeps the parcel visible instead of
        # dropping its sensor. Lives for the integration's lifetime (resets on
        # restart).
        self._raw_cache: dict[str, dict] = {}
        # barcode -> last seen ParcelStatus / (planned_from, planned_to).
        # ``None`` on the first refresh so events are suppressed for parcels
        # that already existed when the integration started — otherwise every
        # restart would flood users with "registered" notifications.
        self._known_state: dict[str, ParcelStatus] | None = None
        self._known_delivery_times: (
            dict[str, tuple[str | None, str | None]] | None
        ) = None
        # Cached device id, attached to every fired event so device-trigger
        # automations can filter to this device.
        self._cached_device_id: str | None = None
        # Timestamp of the last successful poll (diagnostic sensor).
        self.last_success_time: datetime | None = None

    def _device_id(self) -> str | None:
        """Resolve (and cache) this entry's device id for event payloads."""
        if self._cached_device_id is not None:
            return self._cached_device_id
        registry = dr.async_get(self.hass)
        device = next(
            iter(
                dr.async_entries_for_config_entry(registry, self.config_entry.entry_id)
            ),
            None,
        )
        if device is not None:
            self._cached_device_id = device.id
        return self._cached_device_id

    def _tracked(self) -> list[str]:
        """Return the configured tracking codes."""
        return [
            item[CONF_TRACKING_CODE]
            for item in self.config_entry.options.get(CONF_PARCELS, [])
            if item.get(CONF_TRACKING_CODE)
        ]

    @property
    def _include_history(self) -> bool:
        """Whether the opt-in per-parcel history option is enabled."""
        return bool(
            self.config_entry.options.get(
                CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY
            )
        )

    async def _async_update_data(self) -> list[dict]:
        """Fetch every tracked parcel and split into active vs delivered."""
        codes = self._tracked()

        # Drop cache entries for parcels the user no longer follows, so the
        # cache stays bounded.
        tracked_codes = set(codes)
        self._raw_cache = {
            code: raw for code, raw in self._raw_cache.items() if code in tracked_codes
        }

        # One batched request for everything, rather than the per-parcel gather
        # the other suite carriers use. Cainiao's endpoint takes a
        # comma-separated ``mailNos`` list, and a burst of parallel requests is
        # precisely the traffic pattern Alibaba throttles on.
        fetched = await self._client.async_get_parcels(codes)

        raws: list[dict] = []
        for code in codes:
            entry = fetched.get(code)
            if entry is None:
                # Cainiao did not answer for this number. Fall back to the last
                # payload we saw, or to a placeholder so the parcel the user
                # asked us to track stays visible as "unknown" rather than
                # vanishing.
                raws.append(self._raw_cache.get(code) or {"mailNo": code})
                continue

            # An edge payload can come back without its own number; fall back to
            # the one we asked for so the sensor keeps its key.
            entry.setdefault("mailNo", code)
            self._raw_cache[code] = entry
            raws.append(entry)

        include_history = self._include_history
        normalized = [
            normalize_parcel(raw, include_history=include_history) for raw in raws
        ]
        active = [parcel for parcel in normalized if not parcel["delivered"]]
        delivered = [parcel for parcel in normalized if parcel["delivered"]]

        self.delivered = apply_delivered_filter(
            sort_parcels_by_ts(delivered, "delivered_at", descending=True),
            self.config_entry,
        )
        normalized_active = sort_parcels_by_ts(active, "planned_from")

        # Incoming = active + delivered, combined so the transition to
        # delivered is visible in one set.
        incoming = normalized_active + self.delivered
        self._fire_change_events(incoming)
        self._known_state = {
            parcel["barcode"]: parcel["status"]
            for parcel in incoming
            if parcel.get("barcode")
        }
        self._known_delivery_times = {
            parcel["barcode"]: (parcel.get("planned_from"), parcel.get("planned_to"))
            for parcel in incoming
            if parcel.get("barcode")
        }

        # A batched poll either succeeded or raised, so reaching this point is
        # itself the success signal — unlike the per-parcel carriers, there is
        # no "served entirely from cache" case to exclude here.
        self.last_success_time = datetime.now(timezone.utc)
        return normalized_active

    def _fire_change_events(self, parcels: list[dict]) -> None:
        """Fire registered / status-changed / delivered / delivery-time events.

        Silent on the very first refresh — we cannot know which parcels are
        genuinely new versus already present before HA started.

        The event contract, identical across the suite:

        * every payload is the full normalised parcel plus ``device_id``;
        * the hop **to** ``delivered`` fires only ``_parcel_delivered``, never
          also ``_parcel_status_changed``;
        * a barcode first seen already-delivered fires nothing;
        * ``registered`` only fires for a new, not-yet-delivered barcode;
        * an ETA going ``value → null`` is intentionally silent — the carrier
          just lost the window, which is not worth waking someone up for.
        """
        if self._known_state is None:
            return

        known_times = self._known_delivery_times or {}
        device_id = self._device_id()

        for parcel in parcels:
            barcode = parcel.get("barcode")
            if not barcode:
                continue
            new_status = parcel["status"]
            if barcode not in self._known_state:
                if new_status != ParcelStatus.DELIVERED:
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_parcel_registered",
                        {**parcel, "device_id": device_id},
                    )
                continue

            if self._known_state[barcode] != new_status:
                if new_status == ParcelStatus.DELIVERED:
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_parcel_delivered",
                        {**parcel, "device_id": device_id},
                    )
                else:
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_parcel_status_changed",
                        {
                            **parcel,
                            "device_id": device_id,
                            "old_status": self._known_state[barcode],
                            "new_status": new_status,
                        },
                    )

            old_from, old_to = known_times.get(barcode, (None, None))
            new_from = parcel.get("planned_from")
            new_to = parcel.get("planned_to")
            from_changed = new_from is not None and new_from != old_from
            to_changed = new_to is not None and new_to != old_to
            if from_changed or to_changed:
                self.hass.bus.async_fire(
                    f"{DOMAIN}_parcel_delivery_time_changed",
                    {
                        **parcel,
                        "device_id": device_id,
                        "old_planned_from": old_from,
                        "new_planned_from": new_from,
                        "old_planned_to": old_to,
                        "new_planned_to": new_to,
                    },
                )
