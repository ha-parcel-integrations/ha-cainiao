# Working in this repository

Home Assistant custom integration for **Cainiao** parcel tracking. Distributed
via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
Account-less (`track_parcel` / `untrack_parcel` services). No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — the exact key set, units, sort, events and their suppression rules; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client) | *Deliberate skill divergences* |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — without the domain check it deletes the refresh
  button; without the exclusion it deletes the summary/diagnostic sensors. Add a
  new non-parcel sensor's unique_id to that set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

Cainiao is not a national carrier — it is Alibaba's **tracking layer** for
cross-border parcels (AliExpress, Temu, Shein). That shapes everything:

- It sees a parcel from day one, weeks before PostNL/DHL/DPD do — exactly the
  window a user wants tracked.
- The parcel is **handed off** to a national carrier for the last leg, so the
  same box can appear twice in the aggregator (see *Handoff* below).
- Cainiao exposes nothing about the last leg: no sender/receiver/window/pickup/
  weight. The `None`s in `normalize_parcel` are intentional, not unfinished.

### The endpoint

```
GET https://global.cainiao.com/global/detail.json?mailNos={numbers}&lang=en-US
```

Verified live (July 2026):
- **No key, no auth, no bot wall.** Real JSON (`application/json`), not
  `text/plain`.
- **`mailNos` is plural, comma-separated** — one request returns one `module`
  per number, so `api.py` **batches** (`MAX_CODES_PER_REQUEST`, 10) instead of
  fanning out. This is a rate-limit decision, not a micro-opt.
- **An unknown / not-yet-scanned number is NOT an error**: HTTP 200,
  `success:true`, empty `detailList`, no `status`. Treating it as failure would
  make the integration look broken for a parcel's first days.
- A genuine complaint is HTTP 200 `success:false` — `api.py` raises on that.
- `TRACKING_LANGUAGE` stays `en-US` (nl-NL returned identical payloads; stable
  text beats a maybe-missing translation).

### Rate limiting — shapes the integration (non-negotiable without new evidence)

Alibaba soft-bans unusual traffic, and an IP ban costs the user every AliExpress
service. So:
1. **`REFRESH_INTERVAL_MINUTES = 360`, no options-flow field** (generated with
   `--interval fixed`). A parcel crossing a continent for weeks gains nothing
   from a 15-min poll.
2. **One batched request per poll**, never a fan-out — a burst of parallel
   requests is what gets noticed.

The refresh button stays — a single manual poll doesn't flag an IP.

### Payload mapping

| Canonical | Cainiao field |
|---|---|
| `barcode` | `mailNo` |
| `status` | `latestTrace.actionCode`, mapped in `_ACTION_MAP` |
| `raw_status` | `statusDesc`, falling back to `latestTrace.standerdDesc` |
| `delivered_at` | `latestTrace.time`, epoch **milliseconds** |
| `history` | `detailList[]` — `time`, `actionCode`, `standerdDesc`/`desc` |
| (under `raw`) | `destCpInfo.cpName` — the handoff carrier |
| (under `raw`) | `copyRealMailNo` / `realMailNo` — the handoff number |

`standerdDesc` is Cainiao's own spelling, not a typo.

- **Status comes from the action codes, not the `status` token.** The
  `actionCode` vocabulary is published; the summary token's is not.
  `map_parcel_status` reads the newest timeline entry's `actionCode` (fallback:
  last `detailList` entry); the `status` token is only `raw_status` filler.
- `_ACTION_MAP` is cross-checked against two third-party trackers. **Do not add
  mappings without evidence** — a wrong mapping fires events for a state the
  parcel isn't in. Unrecognised code → `unknown` + one-shot warning.
- **Trap: `GTMS_STA_SIGNED` is NOT a delivery** — it's the pickup point signing,
  so it maps to `at_pickup_point`. `GTMS_SIGNED` (no `STA`) is the real one.

### Handoff and double-counting

`destCpInfo.cpName` names the last-leg national carrier; `copyRealMailNo` /
`realMailNo` give its tracking number (`handoff_number()` extracts it). Both stay
**under `raw`** (promoting would be a suite-wide contract change) and are in
`TO_REDACT` (either looks the parcel up publicly). Matching a Cainiao parcel to
its PostNL twin belongs in the aggregator, not here.

### Confidence (pre-1.0)

Verified live: the envelope + empty response. Solid but not captured: the field
names (published schema). Cross-checked not exhaustive: the action-code
vocabulary. Still missing: one fully populated response of our own — treat the
populated shape as well-evidenced, not confirmed. See `TODO.md`.

## Options and reloads — account-less model (do not mix with account-based)

The options flow is **one sectioned form**; changes apply without a restart.
Cainiao is **account-less**, so it uses the **update-listener** model: the
listener retunes `coordinator.update_interval` and calls
`async_request_refresh()`, so added/removed parcel sensors appear immediately.
(Account-based carriers instead call `async_schedule_reload` and register **no**
listener — combining a listener with a reload-on-update flow is deprecated,
error in HA 2026.12+.) Cainiao's fixed cadence means there is no polling option
at all here.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the
gather loop (one bad parcel doesn't fail the poll) but **not** around the whole
update (the coordinator wraps that). Entities: `has_entity_name` +
`translation_key`, `icons.json`, translated units, `_attr_attribution`,
`_unrecorded_attributes` on anything with a parcel list or `raw`. Over-redact
diagnostics — they get pasted into public issues.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (no-ops elsewhere):
`disable_socket` is neutralised (Windows event loops need AF_INET socketpairs;
the 127.0.0.1 allowlist stays) and HA's `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development is Windows.

## Running tests

```
python -m pytest tests/ --cov=custom_components.cainiao
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; `docs/api/` is gitignored (local reverse-engineering notes).
