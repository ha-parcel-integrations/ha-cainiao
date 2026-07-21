"""Constants for the Cainiao parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "cainiao"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# Cainiao's public tracking endpoint — the one its own consumer tracking page
# calls. Verified live (July 2026):
#
# * No key, no auth, no bot wall, and no cookie needed for the request itself
#   (it does hand out aliexpress.com cookies, which we ignore).
# * ``Content-Type: application/json;charset=UTF-8`` — real JSON, unlike the
#   text/plain some consumer endpoints serve.
# * ``mailNos`` is **plural and comma-separated**: one request returns a
#   ``module`` entry per number, in the order asked. That is why the coordinator
#   batches instead of firing one request per parcel — see the rate-limit note
#   below.
# * An unknown or not-yet-scanned number is **not** an error: HTTP 200,
#   ``success: true``, and a module entry with an empty ``detailList`` and no
#   ``status``.
# * ``lang`` selects the language of the human-readable event texts. It accepts
#   ``nl-NL`` but, at least for the numbers probed, the payload came back
#   identical — so English is the safer choice for stable ``raw_status`` text.
TRACKING_API_URL = "https://global.cainiao.com/global/detail.json"

# How many tracking numbers to put in one request. Cainiao documents no limit;
# 10 keeps the URL short and the blast radius of one failed request small.
MAX_CODES_PER_REQUEST = 10

# Language for the event texts (``statusDesc`` and the history entries).
TRACKING_LANGUAGE = "en-US"

# Consumer tracking deep link for the parcel's ``url`` field.
TRACKING_URL = "https://global.cainiao.com/detail.htm?mailNoList={tracking_code}"

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code}`` dicts — this carrier has no account or parcel feed, so the
# user enters the codes themselves. Kept as dicts so future per-parcel fields
# slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Polling cadence, in minutes. **Six hours, and deliberately not configurable.**
#
# This is the one place where Cainiao diverges from every other carrier in the
# suite, which all expose a 15/30/60/120/240-minute option. Alibaba throttles
# and soft-bans traffic it considers unusual, and an IP ban costs the user every
# AliExpress service, not just this integration. A parcel that spends three
# weeks crossing a continent gains nothing from being asked about every fifteen
# minutes, so there is no upside to trade against that risk.
#
# The refresh button still exists for the impatient — a single manual poll is
# not what gets an IP flagged.
REFRESH_INTERVAL_MINUTES = 360

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Cainiao ships the whole timeline (``detailList``) in the same response,
# so enabling it costs no extra request — it stays off by default only because
# it is a large attribute. Cross-border parcels accumulate a lot of events.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
