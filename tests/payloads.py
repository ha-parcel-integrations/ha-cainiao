"""Sample Cainiao API payloads shared by the test modules.

Shaped after the live endpoint. The **empty** case below is verbatim from a real
response (July 2026). The populated ones are built from the documented response
schema and the published ``actionCode`` vocabulary; the field *names* are solid,
but no fully populated response has been captured yet — see TODO.md.
"""
from __future__ import annotations

ACTIVE_CODE = "LP00999999999"
DELIVERED_CODE = "LP00123456789"

# Verbatim from the live endpoint for a number it does not know. Note that this
# is a *success* response: HTTP 200, ``success: true``, and simply no events.
UNKNOWN_MODULE_ENTRY = {
    "mailNo": "LP00000000000",
    "mailNoSource": "EXTERNAL",
    "detailList": [],
}


def trace(action_code: str, time_ms: int, desc: str) -> dict:
    """One entry of Cainiao's ``detailList`` timeline."""
    return {
        "actionCode": action_code,
        "time": time_ms,
        "timeStr": "2026-04-26 10:40:00",
        "timeZone": "GMT+02:00",
        "desc": desc,
        "standerdDesc": desc,  # Cainiao's spelling, not ours
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A module entry for a delivered parcel."""
    return {
        "mailNo": code,
        "mailNoSource": "EXTERNAL",
        "status": "delivered",
        "statusDesc": "Delivered",
        "originCountry": "CN",
        "destCountry": "NL",
        "daysNumber": "18",
        "copyRealMailNo": "3SDFC0123456789",
        "realMailNo": "PostNL 3SDFC0123456789",
        "destCpInfo": {"cpName": "PostNL", "cpCode": "POSTNL"},
        "latestTrace": trace("GTMS_SIGNED", 1_777_200_000_000, "Delivered"),
        "detailList": [
            trace("GTMS_SIGNED", 1_777_200_000_000, "Delivered"),
            trace("GTMS_DO_DEPART", 1_777_100_000_000, "Out for delivery"),
            trace("LH_ARRIVE", 1_776_000_000_000, "Arrived at destination country"),
            trace("LH_DEPART", 1_774_000_000_000, "Departed from origin country"),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A module entry for a parcel still in transit."""
    sample = delivered_sample(code)
    sample.update(
        {
            "status": "transport",
            "statusDesc": "In transit",
            "latestTrace": trace(
                "LH_DEPART", 1_774_000_000_000, "Departed from origin country"
            ),
            "detailList": sample["detailList"][2:],
        }
    )
    return sample


def pickup_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel signed for by a pickup point — *not* delivered to the recipient.

    The distinction matters: ``GTMS_STA_SIGNED`` looks like a signature but is
    the station accepting the parcel, so it must not fire the delivered event.
    """
    sample = active_sample(code)
    sample.update(
        {
            "status": "pickup",
            "statusDesc": "Ready for collection",
            "latestTrace": trace(
                "GTMS_STA_SIGNED", 1_777_150_000_000, "Arrived at pickup point"
            ),
        }
    )
    return sample


def response(*entries: dict) -> dict:
    """Wrap module entries in the endpoint's envelope."""
    return {"module": list(entries), "success": True}


def as_map(*entries: dict) -> dict[str, dict]:
    """What ``CainiaoApiClient.async_get_parcels`` returns: keyed by number."""
    return {entry["mailNo"]: entry for entry in entries}
