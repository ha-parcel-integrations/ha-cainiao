"""Sample Cainiao API payloads shared by the test modules.

Shaped after the live endpoint. The **empty** case below is verbatim from a real
response (July 2026); the populated ones are built from the documented field
names and are the part that still needs confirming against a real parcel — see
TODO.md.
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
        "copyRealMailNo": "3SDFC0123456789",
        "realMailNo": "PostNL 3SDFC0123456789",
        "destCpInfo": {"cpName": "PostNL", "cpCode": "POSTNL"},
        "latestTrace": {
            "actionCode": "SIGNIN",
            "time": 1_777_200_000_000,
            "desc": "Delivered",
            "standerdDesc": "Delivered",
        },
        "detailList": [
            trace("SIGNIN", 1_777_200_000_000, "Delivered"),
            trace("DELIVERING", 1_777_100_000_000, "Out for delivery"),
            trace("ARRIVAL", 1_776_000_000_000, "Arrived at destination country"),
            trace("DEPARTURE", 1_774_000_000_000, "Departed from origin country"),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A module entry for a parcel still in transit."""
    sample = delivered_sample(code)
    sample.update(
        {
            "status": "transport",
            "statusDesc": "In transit",
            "latestTrace": {
                "actionCode": "DEPARTURE",
                "time": 1_774_000_000_000,
                "desc": "Departed from origin country",
                "standerdDesc": "Departed from origin country",
            },
            "detailList": sample["detailList"][2:],
        }
    )
    return sample


def response(*entries: dict) -> dict:
    """Wrap module entries in the endpoint's envelope."""
    return {"module": list(entries), "success": True}


def as_map(*entries: dict) -> dict[str, dict]:
    """What ``CainiaoApiClient.async_get_parcels`` returns: keyed by number."""
    return {entry["mailNo"]: entry for entry in entries}
