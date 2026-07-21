# Cainiao — still to do

The integration is complete and its tests pass, but **the populated payload
mapping has never been checked against a real parcel**. Only the empty /
unknown-number response was verified live (July 2026). Until that changes,
treat what follows as the gap between "builds" and "works".

## Before a 1.0.0 release

- [ ] **Track one real parcel through at least two statuses.** Order a cheap
      AliExpress item, add its `LP…` number, and watch it move. This is the
      only step that can turn the assumptions below into facts.
- [ ] **Extend the action-code vocabulary.** `_ACTION_MAP` in `parcels.py` holds
      31 codes, cross-checked between two maintained third-party trackers — but
      it is not exhaustive. Every unmapped code logs a one-shot warning with the
      exact line to paste into an issue; collect those. **Do not add mappings
      you have not seen evidence for.**
- [ ] **Sanity-check the pickup codes against a real parcel.**
      `GTMS_STA_SIGNED` / `GTMS_WAIT_SELF_PICK` / `GSTA_INFORM_BUYER` map to
      `at_pickup_point`, which is the one group where a wrong call is
      user-visible: it decides whether the delivered event fires.
- [ ] **Check whether an ETA is ever exposed.** `planned_from` / `planned_to`
      are hard-coded to `None` because nothing in the probed responses carried
      a window. If a real parcel does, wire it up — the calendar and the
      `next_delivery` sensor only come alive when it exists, and
      `test_delivery_time_events_never_fire` is the test that will start
      failing.
- [ ] **Probe `MAX_CODES_PER_REQUEST`.** Ten per request is a guess at a safe
      batch size; Cainiao documents no limit. Worth knowing before someone
      tracks thirty parcels.
- [ ] **Replace the sample payloads** in `tests/payloads.py` with real,
      redacted responses.

## Already verified live

- The endpoint, its envelope, batching via comma-separated `mailNos`, the
  `Content-Type`, and that an unknown number returns HTTP 200 with
  `success: true` and an empty `detailList`.
- Six-hour fixed cadence and one batched request per poll — the rate-limit
  strategy, see `CLAUDE.md`.

## Suite integration

- [ ] Add `cainiao` to the aggregator's `KNOWN_CARRIERS` and
      `CARRIER_EVENT_PREFIXES`.
- [ ] Decide whether the aggregator should dedupe on the handoff number
      (`handoff_number()` in `parcels.py`), so one physical parcel is not
      counted twice — once as Cainiao, once as the local carrier delivering the
      last leg. That is an aggregator decision, not a Cainiao one.

Delete this file once it is empty.
