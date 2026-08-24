"""Sample Cainiao API payloads shared by the test modules.

Shaped after the live endpoint. The **empty** case below is verbatim from a real
response (July 2026). ``delivered_sample``/``active_sample``/``pickup_sample``
are built from the documented response schema and the published ``actionCode``
vocabulary. ``real_delivered_sample``/``real_active_sample`` are redacted but
otherwise verbatim real payloads from a user's diagnostics export (2026-08-24,
see ``carrier-research/cainiao/``) — only ``mailNo`` and its handoff-number
counterparts are replaced with placeholders.
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
        "globalEtaInfo": {
            "etaDesc": "Estimated delivery by",
            "deliveryMinTime": 1_787_800_000_000,
            "deliveryMaxTime": 1_787_900_000_000,
        },
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


def real_delivered_sample() -> dict:
    """A real, delivered cross-border parcel — from a user's diagnostics export
    (2026-08-24), redacted. ``mailNo`` is replaced with a placeholder; every
    other field, including ones this module does not map (``processInfo``,
    ``globalCombinedLogisticsTraceDTO``, ``descTitle``, ``daysNumber``'s
    embedded tab) is verbatim. Icon URLs are stripped for size — they carry no
    logic — everything else is unmodified.

    This is the response issue #6 asked for: real evidence, not a guessed
    shape. It independently confirms ``GTMS_SIGNED`` → delivered,
    ``GTMS_DO_DEPART`` → out_for_delivery, ``GTMS_OE_DEPART`` and
    ``CC_IM_SUCCESS`` → in_transit, and that ``copyRealMailNo``/``realMailNo``/
    ``destCpInfo`` can all be absent at once (this parcel never got handed to a
    national carrier before delivery — no last-mile handoff to report).
    """
    return {
        "mailNo": "RC000000001EE",
        "originCountry": "Mainland China",
        "destCountry": "Belgium",
        "status": "DELIVERED",
        "statusDesc": "Delivered",
        "mailNoSource": "AE",
        "processInfo": {
            "progressStatus": "NORMAL",
            "progressRate": 1.0,
            "type": "CROSS",
            "progressPointList": [
                {"pointName": "Mainland China", "light": True},
                {"pointName": "Belgium", "light": True},
                {"pointName": "Destination city", "light": True},
                {"pointName": "Delivered", "light": True},
            ],
        },
        "globalCombinedLogisticsTraceDTO": {
            "time": 1_770_362_717_000,
            "timeStr": "2026-02-06 15:25:17",
            "desc": "Parcel delivered",
            "standerdDesc": "Package delivered",
            "descTitle": "Carrier note:",
            "timeZone": "GMT+08:00",
            "actionCode": "GTMS_SIGNED",
            "group": {"nodeCode": "AE_GROUP_DELIVERED", "nodeDesc": "Delivered"},
        },
        "latestTrace": {
            "time": 1_770_362_717_000,
            "timeStr": "2026-02-06 15:25:17",
            "desc": "Parcel delivered",
            "standerdDesc": "Package delivered",
            "descTitle": "Carrier note:",
            "timeZone": "GMT+08:00",
            "actionCode": "GTMS_SIGNED",
            "group": {"nodeCode": "AE_GROUP_DELIVERED", "nodeDesc": "Delivered"},
        },
        "detailList": [
            {
                "time": 1_770_362_717_000,
                "timeStr": "2026-02-06 15:25:17",
                "desc": "Parcel delivered",
                "standerdDesc": "Package delivered",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "GTMS_SIGNED",
                "group": {"nodeCode": "AE_GROUP_DELIVERED", "nodeDesc": "Delivered"},
            },
            {
                "time": 1_770_335_562_000,
                "timeStr": "2026-02-06 07:52:42",
                "desc": "Out for delivery abroad",
                "standerdDesc": "Out for delivery",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "GTMS_DO_DEPART",
                "group": {"nodeCode": "AE_GROUP_DELIVERING", "nodeDesc": "Out for delivery"},
            },
            {
                "time": 1_770_197_545_000,
                "timeStr": "2026-02-04 17:32:25",
                "desc": "Custom clearance completed",
                "standerdDesc": "Import customs clearance complete",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "CC_IM_SUCCESS",
                "group": {"nodeCode": "AE_GROUP_IM_CLEARING_CUSTOMS", "nodeDesc": "At customs"},
            },
            {
                "time": 1_770_013_388_000,
                "timeStr": "2026-02-02 14:23:08",
                "desc": "wait for customs clearance",
                "standerdDesc": "Shipment on the way",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "COMMON_INTRANSIT",
            },
            {
                "time": 1_769_410_384_000,
                "timeStr": "2026-01-26 14:53:04",
                "desc": "Arrived at the station",
                "standerdDesc": "Arrived at linehaul office",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "LH_ARRIVE",
                "group": {"nodeCode": "AE_GROUP_LH_ARRIVE", "nodeDesc": "In transit"},
            },
            {
                "time": 1_765_205_062_000,
                "timeStr": "2025-12-08 22:44:22",
                "desc": "Shipment departed from facility",
                "standerdDesc": "Carrier update",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "GTMS_OE_DEPART",
                "group": {"nodeCode": "AE_GROUP_DES_PROCESSING", "nodeDesc": "In transit"},
            },
            {
                "time": 1_765_204_140_000,
                "timeStr": "2025-12-08 22:29:00",
                "desc": "Shipment picked up",
                "standerdDesc": "Received by logistics company",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+08:00",
                "actionCode": "PU_PICKUP_SUCCESS",
            },
        ],
        "daysNumber": "60\tday(s)",
    }


def real_active_sample() -> dict:
    """A real, still-in-customs cross-border parcel — same diagnostics export
    (2026-08-24), redacted. ``mailNo``/``copyRealMailNo``/``realMailNo`` are
    placeholders; everything else is verbatim, including ``globalEtaInfo``
    where ``deliveryMinTime`` and ``deliveryMaxTime`` are identical — a point
    estimate, not a window, on every real payload seen so far.
    """
    return {
        "mailNo": "RC000000002EE",
        "realMailNo": "Latest Tracking Number:\tRC000000003EE",
        "originCountry": "Mainland China",
        "destCountry": "Ukraine",
        "status": "CLEAR_CUSTOMS",
        "statusDesc": "In customs ",
        "mailNoSource": "AE",
        "globalEtaInfo": {
            "etaDesc": "Estimated delivery by",
            "deliveryMinTime": 1_787_828_878_899,
            "deliveryMaxTime": 1_787_828_878_899,
        },
        "latestTrace": {
            "time": 1_787_465_920_000,
            "timeStr": "2026-08-23 14:18:40",
            "desc": "Leaving customs",
            "standerdDesc": "Departed from customs",
            "descTitle": "Carrier note:",
            "timeZone": "GMT+2",
            "actionCode": "CC_HO_OUT_SUCCESS",
            "group": {"nodeCode": "AE_GROUP_EX_CLEARING_CUSTOMS", "nodeDesc": "At customs"},
        },
        "detailList": [
            {
                "time": 1_787_465_920_000,
                "timeStr": "2026-08-23 14:18:40",
                "desc": "Leaving customs",
                "standerdDesc": "Departed from customs",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+2",
                "actionCode": "CC_HO_OUT_SUCCESS",
                "group": {"nodeCode": "AE_GROUP_EX_CLEARING_CUSTOMS", "nodeDesc": "At customs"},
            },
            {
                "time": 1_787_400_180_000,
                "timeStr": "2026-08-22 20:03:00",
                "desc": "Accepted for transportation by postal service",
                "standerdDesc": "Accepted for transportation by postal service",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+3",
                "actionCode": "LH_POST_COLLECTION",
                "group": {"nodeCode": "AE_GROUP_LH_PROCESSING", "nodeDesc": "In transit"},
            },
            {
                "time": 1_783_018_517_000,
                "timeStr": "2026-07-03 02:55:17",
                "desc": "Outbound in sorting center",
                "standerdDesc": "[Xiaoshan District] Departed from sorting center",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+8",
                "actionCode": "SC_OUTBOUND_SUCCESS",
                "group": {"nodeCode": "AE_GROUP_SC_PROCESSING", "nodeDesc": "In transit"},
            },
            {
                "time": 1_782_922_591_000,
                "timeStr": "2026-07-02 00:16:31",
                "desc": "Accepted by carrier",
                "standerdDesc": "Received by logistics company",
                "descTitle": "Carrier note:",
                "timeZone": "GMT+8",
                "actionCode": "PU_PICKUP_SUCCESS",
            },
        ],
        "daysNumber": "55\tday(s)",
    }


def response(*entries: dict) -> dict:
    """Wrap module entries in the endpoint's envelope."""
    return {"module": list(entries), "success": True}


def as_map(*entries: dict) -> dict[str, dict]:
    """What ``CainiaoApiClient.async_get_parcels`` returns: keyed by number."""
    return {entry["mailNo"]: entry for entry in entries}
