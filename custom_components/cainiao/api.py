"""Cainiao public tracking API client.

One endpoint, no auth, and — unusually for this suite — **batched**: Cainiao's
``mailNos`` parameter takes a comma-separated list and answers with one module
entry per number. Every other carrier here polls one parcel per request; doing
that against Cainiao is exactly the "unusual traffic" Alibaba throttles on, so
this client asks about everything at once.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import MAX_CODES_PER_REQUEST, TRACKING_API_URL, TRACKING_LANGUAGE

_LOGGER = logging.getLogger(__name__)


class CainiaoApiError(Exception):
    """Raised when a Cainiao API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cainiao API request failed: {detail}")
        self.detail = detail


def _chunk(codes: list[str], size: int) -> list[list[str]]:
    """Split ``codes`` into batches of at most ``size``."""
    return [codes[start : start + size] for start in range(0, len(codes), size)]


class CainiaoApiClient:
    """Client for Cainiao's public tracking endpoint.

    No authentication: the endpoint is keyed on the tracking number alone. It
    answers HTTP 200 with::

        {"module": [{"mailNo": "...", "detailList": [...], "status": "..."}],
         "success": true}

    An unknown or not-yet-scanned number is *not* an error — it comes back as a
    module entry with an empty ``detailList`` and no ``status``. Telling that
    apart from a failure is most of this class's job: a cross-border parcel
    routinely sits in that state for days right after ordering, and reporting it
    as an outage would make the integration look broken exactly when users are
    watching it most closely.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcels(
        self, tracking_codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Fetch several parcels at once, keyed by tracking number.

        Returns a ``{tracking_code: module_entry}`` mapping. Numbers Cainiao
        does not answer for are simply absent; the caller decides what to show
        for them. Raises :class:`CainiaoApiError` on a malformed response or an
        unsuccessful envelope; network errors propagate as
        ``aiohttp.ClientError``.
        """
        parcels: dict[str, dict[str, Any]] = {}
        for batch in _chunk(tracking_codes, MAX_CODES_PER_REQUEST):
            parcels.update(await self._async_get_batch(batch))
        return parcels

    async def _async_get_batch(self, batch: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch one batch of tracking numbers."""
        params = {"mailNos": ",".join(batch), "lang": TRACKING_LANGUAGE}
        async with self._session.get(TRACKING_API_URL, params=params) as response:
            if response.status != 200:
                raise CainiaoApiError(f"HTTP {response.status}")
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise CainiaoApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise CainiaoApiError("unexpected body (not a JSON object)")
        if not payload.get("success"):
            # The envelope carries its own success flag; a false one alongside
            # HTTP 200 is how this endpoint reports being unhappy with us.
            raise CainiaoApiError(
                str(
                    payload.get("errorCode")
                    or payload.get("errorMsg")
                    or "success=false"
                )
            )

        module = payload.get("module")
        if not isinstance(module, list):
            raise CainiaoApiError("unexpected body (no module list)")

        parcels: dict[str, dict[str, Any]] = {}
        for entry in module:
            if not isinstance(entry, dict):
                continue
            mail_no = entry.get("mailNo")
            if isinstance(mail_no, str) and mail_no:
                parcels[mail_no] = entry
        return parcels
