"""Tests for the Cainiao API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.cainiao.api import CainiaoApiClient, CainiaoApiError

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    UNKNOWN_MODULE_ENTRY,
    active_sample,
    delivered_sample,
    response,
)


def _session_returning(status: int, body: object = None) -> MagicMock:
    resp = AsyncMock()
    resp.status = status
    if isinstance(body, str):
        resp.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        resp.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcels_returns_entries_keyed_by_number():
    session = _session_returning(200, response(active_sample(), delivered_sample()))
    client = CainiaoApiClient(session)

    parcels = await client.async_get_parcels([ACTIVE_CODE, DELIVERED_CODE])

    assert set(parcels) == {ACTIVE_CODE, DELIVERED_CODE}
    assert parcels[ACTIVE_CODE]["status"] == "transport"


async def test_get_parcels_sends_one_comma_separated_request():
    """Batching is the rate-limit strategy — one request, not one per parcel."""
    session = _session_returning(200, response(active_sample(), delivered_sample()))
    client = CainiaoApiClient(session)

    await client.async_get_parcels([ACTIVE_CODE, DELIVERED_CODE])

    assert session.get.call_count == 1
    params = session.get.call_args[1]["params"]
    assert params["mailNos"] == f"{ACTIVE_CODE},{DELIVERED_CODE}"
    assert params["lang"] == "en-US"


async def test_get_parcels_splits_into_batches():
    session = _session_returning(200, response())
    client = CainiaoApiClient(session)

    await client.async_get_parcels([f"LP000000000{n:03d}" for n in range(25)])

    # 25 numbers at 10 per request.
    assert session.get.call_count == 3


async def test_get_parcels_with_nothing_tracked_makes_no_request():
    session = _session_returning(200, response())
    client = CainiaoApiClient(session)

    assert await client.async_get_parcels([]) == {}
    assert session.get.call_count == 0


async def test_unknown_number_comes_back_as_an_entry_not_an_error():
    """A not-yet-scanned cross-border parcel is normal, not a failure."""
    session = _session_returning(200, response(UNKNOWN_MODULE_ENTRY))
    client = CainiaoApiClient(session)

    parcels = await client.async_get_parcels(["LP00000000000"])

    assert parcels["LP00000000000"]["detailList"] == []
    assert "status" not in parcels["LP00000000000"]


async def test_entries_without_a_number_are_skipped():
    session = _session_returning(200, response({"detailList": []}, "junk"))
    client = CainiaoApiClient(session)
    assert await client.async_get_parcels([ACTIVE_CODE]) == {}


async def test_raises_on_error_status():
    client = CainiaoApiClient(_session_returning(503, {}))
    with pytest.raises(CainiaoApiError):
        await client.async_get_parcels([ACTIVE_CODE])


async def test_raises_on_unsuccessful_envelope():
    """HTTP 200 with success=false is how the endpoint reports being unhappy."""
    client = CainiaoApiClient(
        _session_returning(200, {"success": False, "errorCode": "RATE_LIMIT"})
    )
    with pytest.raises(CainiaoApiError) as err:
        await client.async_get_parcels([ACTIVE_CODE])
    assert "RATE_LIMIT" in str(err.value)


async def test_raises_on_unsuccessful_envelope_without_detail():
    client = CainiaoApiClient(_session_returning(200, {"success": False}))
    with pytest.raises(CainiaoApiError):
        await client.async_get_parcels([ACTIVE_CODE])


async def test_raises_on_unparseable_body():
    client = CainiaoApiClient(_session_returning(200, "not json"))
    with pytest.raises(CainiaoApiError):
        await client.async_get_parcels([ACTIVE_CODE])


async def test_raises_on_non_object_body():
    client = CainiaoApiClient(_session_returning(200, ["nope"]))
    with pytest.raises(CainiaoApiError):
        await client.async_get_parcels([ACTIVE_CODE])


async def test_raises_without_a_module_list():
    client = CainiaoApiClient(_session_returning(200, {"success": True}))
    with pytest.raises(CainiaoApiError):
        await client.async_get_parcels([ACTIVE_CODE])


async def test_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    with pytest.raises(aiohttp.ClientError):
        await CainiaoApiClient(session).async_get_parcels([ACTIVE_CODE])
