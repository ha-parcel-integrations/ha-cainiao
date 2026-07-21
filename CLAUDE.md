# Working in this repository

This is a Home Assistant custom integration for **Cainiao** parcel
tracking. Distributed via HACS; not part of HA core. It is one carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite and
publishes the same canonical parcel shape, statuses and events as the others,
so the aggregator and cross-carrier dashboards can read every carrier
identically.

It was generated from **ha-carrier-template**. Everything outside the
*Carrier-specific notes* section is suite-wide; when in doubt, check the
template or a sibling repo rather than inventing something new.

## Always consult HA developer documentation

Home Assistant's integration patterns evolve continuously. **Do not rely on
memory of past patterns** — fetch the canonical page before changing a topic
area, and check the developer blog before introducing anything you only "know"
from training data.

| When you change | Fetch first |
|---|---|
| Entity properties, naming, lifecycle, attributes | https://developers.home-assistant.io/docs/core/entity/ |
| Sensor specifics (state/device classes, units) | https://developers.home-assistant.io/docs/core/entity/sensor |
| Config flow, options flow, reauth, reconfigure | https://developers.home-assistant.io/docs/config_entries_config_flow_handler |
| DataUpdateCoordinator pattern | https://developers.home-assistant.io/docs/integration_fetching_data |
| Quality scale rules | https://developers.home-assistant.io/docs/core/integration-quality-scale |
| Diagnostics | https://developers.home-assistant.io/docs/core/integration/diagnostics |
| Translations | https://developers.home-assistant.io/docs/internationalization/core |

Recent developer-facing changes worth checking before introducing a pattern
from training data:

- https://developers.home-assistant.io/blog — API deprecations, new patterns,
  breaking changes. Recent posts trump older recollection.
- https://github.com/home-assistant/architecture/discussions — design decisions
  in flight that have not reached stable docs yet.

Branding is handled by the local `custom_components/cainiao/brand/`
folder (HACS reads `icon.png` from it). The official `home-assistant/brands`
repo is for HA Core integrations and does not apply here.

## Carrier-specific notes

Cainiao is not a national carrier. It is Alibaba's **tracking layer** for
cross-border parcels — AliExpress, Temu, Shein and the rest of the cheap
China→Europe flow. That shapes almost every decision here:

- A cross-border parcel is invisible to PostNL/DHL/DPD until it reaches the
  Dutch network, often two weeks after ordering. Cainiao sees it from day one,
  which is exactly the window a user wants tracked.
- The parcel is **handed off** to a national carrier for the last leg. So the
  same physical parcel can appear twice in the aggregator, once as Cainiao and
  once as the local carrier. See *Handoff and double-counting* below.
- Cainiao exposes nothing about the last leg: no sender, no receiver, no
  delivery window, no pickup point, no weight. The `None`s in
  `normalize_parcel` are intentional, not unfinished.

### The endpoint

```
GET https://global.cainiao.com/global/detail.json?mailNos={numbers}&lang=en-US
```

Verified live, July 2026:

- **No key, no auth, no bot wall.** It hands out `aliexpress.com` cookies,
  which we ignore.
- `Content-Type: application/json;charset=UTF-8` — real JSON, not the
  `text/plain` some consumer endpoints serve.
- **`mailNos` is plural and comma-separated.** One request returns one `module`
  entry per number. This is why `api.py` batches (`MAX_CODES_PER_REQUEST`,
  currently 10) instead of firing one request per parcel like every other
  carrier in the suite. That is not a micro-optimisation — see *Rate limiting*.
- **An unknown or not-yet-scanned number is not an error.** HTTP 200,
  `success: true`, and a module entry with an empty `detailList` and no
  `status`. Treating that as a failure would make the integration look broken
  for the first days of every parcel's life, which is precisely when people are
  watching it.
- A genuine complaint comes back as HTTP 200 with `success: false`; `api.py`
  raises on that.
- `lang` selects the language of the event texts. `nl-NL` is accepted but
  returned identical payloads for the numbers probed, so `TRACKING_LANGUAGE`
  stays `en-US` — stable text beats a translation that may not exist.

### Rate limiting — the constraint that shapes the integration

Alibaba throttles and soft-bans traffic it considers unusual, and an IP ban
costs the user every AliExpress service, not just this integration.

Two decisions follow, and **neither is negotiable without new evidence**:

1. **`REFRESH_INTERVAL_MINUTES = 360`, with no options-flow field.** Every
   other carrier in the suite offers 15/30/60/120/240 minutes. This one does
   not, and the integration is generated with `--interval fixed` for that
   reason. A parcel that spends three weeks crossing a continent gains nothing
   from being asked about every fifteen minutes.
2. **One batched request per poll**, not a fan-out. A burst of parallel
   requests every few hours is the shape that gets noticed.

The refresh button still exists — a single manual poll is not what gets an IP
flagged.

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

`standerdDesc` is Cainiao's own spelling, not a typo in this repo.

**Status comes from the action codes, not from the `status` token.** Cainiao
sends a parcel-level `status` summary *and* a per-event `actionCode`. The action
codes are a specific, published vocabulary; the summary token's is not, so
`map_parcel_status` reads the newest timeline entry's `actionCode` (falling back
to the last `detailList` entry when `latestTrace` is absent) and the `status`
token is only used as `raw_status` filler.

`_ACTION_MAP` is cross-checked against two independently maintained third-party
trackers that call this endpoint. Still, an unrecognised code surfaces as
`unknown` plus a one-shot warning, so the map grows from real reports. **Do not
add mappings you have not seen evidence for** — a wrong mapping is worse than a
missing one, because it fires events for a state the parcel is not in.

One trap worth knowing: **`GTMS_STA_SIGNED` is not a delivery.** It is the
pickup point signing for the parcel, so it maps to `at_pickup_point`. Mapping it
to `delivered` would fire the delivered event while the parcel sits in a locker.
`GTMS_SIGNED` — no `STA` — is the real one.

### Handoff and double-counting

`destCpInfo.cpName` names the national carrier that delivers the last leg, and
`copyRealMailNo` / `realMailNo` give that carrier's own tracking number.
`handoff_number()` extracts it.

That number stays **under `raw`**, not promoted to a top-level canonical key.
Promoting it would be a suite-wide contract change, and the interesting use —
letting the aggregator recognise that a Cainiao parcel and a PostNL parcel are
the same physical box — belongs in the aggregator, not here. Worth designing
for; not worth unilaterally changing the contract for.

Both numbers are in `TO_REDACT`: either one is enough to look the parcel up on
a public tracking page.

### Confidence levels

Three different things, three different levels of certainty:

1. **The envelope and the empty response** — verified live against the endpoint.
2. **The field names** — from the published response schema (`mailNo`, `status`,
   `statusDesc`, `latestTrace`, `detailList[].actionCode|time|timeStr|timeZone|
   desc|standerdDesc`, `destCpInfo`, `originCountry`, `destCountry`). Solid, but
   not read off a response we captured.
3. **The action-code vocabulary** — cross-checked between two maintained
   trackers, so unlikely to be wrong, but not exhaustive.

What is still missing is a single fully populated response of our own. Until one
exists, treat the populated shape as well-evidenced rather than confirmed. See
`TODO.md`.

## The canonical parcel contract

Every carrier publishes parcels through `normalize_parcel` in `parcels.py`
with **exactly** these top-level keys, in this order:

`carrier`, `barcode`, `sender`, `receiver`, `status`, `raw_status`,
`delivered`, `delivered_at`, `planned_from`, `planned_to`, `pickup`,
`pickup_point`, `url`, `weight`, `dimensions`, `history`, `raw`.

- A key the carrier does not expose is `None` — **never omitted**. Consumers
  read the key unconditionally.
- Carrier-specific extras live under `raw`. The aggregator strips `raw`, so
  anything that must survive aggregation has to be top-level.
- `status` is the canonical `ParcelStatus` enum; `raw_status` is the carrier's
  own text. Do not put the carrier's string on `status`.
- **Units**: `weight` in kilograms (float); `dimensions` in centimetres as
  `{length, width, height, text}` where `text` is `"L x W x H cm"` (integers,
  lowercase `x`). Convert before normalising if the carrier reports grams or
  millimetres.
- **Sort contract**: incoming ascending on `planned_from`, delivered descending
  on `delivered_at`, missing timestamps always last (`sort_parcels_by_ts`).
- Summary sensors expose the list under the `parcels` attribute — never
  `shipments`.

`test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards
the key set. Changing it is a suite-wide change: every carrier plus the
aggregator, together.

## Events

Fired on the HA bus by the coordinator, and exposed as no-code device triggers
via `device_trigger.py`:

| Event | When |
|---|---|
| `cainiao_parcel_registered` | A new, not-yet-delivered barcode appears |
| `cainiao_parcel_status_changed` | Canonical status changed (carries `old_status` / `new_status`) |
| `cainiao_parcel_delivered` | A parcel reached `delivered` |
| `cainiao_parcel_delivery_time_changed` | `planned_from` / `planned_to` changed |

Rules that are easy to break and must not be:

- **Events are suppressed on the very first refresh** (`_known_state is None`).
  Without this, every HA restart floods users with "registered" events for
  parcels that already existed.
- Events run over the **active + delivered set combined**, so the terminal hop
  is visible in one pass.
- The hop **to** `delivered` fires only `_parcel_delivered`, never also
  `_parcel_status_changed`. A barcode first seen already-delivered fires
  nothing.
- An ETA going `value → null` is **intentionally silent** — the carrier merely
  lost the window; not worth waking someone up for.
- Every payload is the full normalised parcel plus `device_id` (resolved once
  and cached in `_cached_device_id`). `device_id` is what lets device triggers
  filter per hub.

## Architecture rules

- **`ConfigEntry.runtime_data`** with a typed dataclass; no `hass.data`.
- **The first refresh runs in `__init__.py`, before
  `async_forward_entry_setups`.** Raising `ConfigEntryNotReady` from a
  *forwarded* platform is too late for HA to catch: it logs a warning and
  half-sets-up the entry, and users end up with some platforms and no sensors.
  Never move the first refresh into a platform.
- **`PARALLEL_UPDATES = 0`** in every platform — the coordinator already
  handles fan-out.
- The coordinator takes `config_entry=entry`, so `self.config_entry` works.
- `aiohttp.ClientError` is deliberately **not** caught around the whole update
  — `DataUpdateCoordinator` wraps it into `UpdateFailed` already. It *is*
  caught per parcel in the gather loop, so one bad parcel does not fail the
  whole poll.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove(entity_id)` when a barcode drops out of the
  coordinator data. Self-removal races with coordinator-listener cleanup and
  leaves ghost entities behind.
- **The setup-time stale-entity sweep in `sensor.py` is scoped to
  `entity_entry.domain == "sensor"`** and skips every unique_id in
  `non_parcel_unique_ids`. Without the domain check it deletes the refresh
  button; without the exclusion set it deletes the summary and diagnostic
  sensors. When you add a non-parcel sensor, add its unique_id to that set.
- **`has_entity_name = True` + `translation_key`** on every entity. Names come
  from `strings.json` and the translation files — no `_attr_name`. Icons come
  from `icons.json` — no `_attr_icon`. Units come from
  `entity.sensor.<key>.unit_of_measurement` — no
  `_attr_native_unit_of_measurement`.
- **`_unrecorded_attributes`** on anything carrying a parcel list or a `raw`
  payload, so the recorder's long-term tables stay small.
- `_attr_attribution` on every entity.
- **Unmapped statuses log a one-shot WARNING** per distinct value with a
  copy-paste `issues/new` link; users report them through the *Unrecognised
  parcel status* issue template. That is how the status map grows.
- Diagnostics redact every identifying field — they get pasted into public
  issues. Over-redact rather than under-redact.
- Network calls return raw JSON dicts; there is no DTO layer.

## Options and reloads

The options flow is **one sectioned form** (`data_entry_flow.section`), and
changes apply without a restart. Two models, do not mix them:

- **Account-less carriers** (this one) apply changes live: an update listener
  retunes `coordinator.update_interval` and calls `async_request_refresh()`, so
  added and removed parcel sensors appear immediately.
- **Account-based carriers** call `async_schedule_reload` on submit and
  register **no** update listener. Combining an update listener with a
  reload-on-update flow is deprecated today and an error in HA 2026.12+ — see
  the [config_entry_listener deprecation](https://developers.home-assistant.io/blog/2026/05/07/config-entry-listener-together-with-reloading-methods/).

A user-tunable polling interval is a **deliberate divergence** from the HA Core
rule that polling intervals are not configurable: that rule targets core
integrations, and in a HACS parcel tracker a tunable cadence is a wanted
feature. Carriers that throttle or soft-ban unusual traffic are generated with
a fixed cadence instead and have no polling option at all.

## Module layout

| File | Contains | Carrier-specific? |
|---|---|---|
| `api.py` | HTTP client, error types | **yes** |
| `const.py` | Domain, URLs, `ParcelStatus`, option keys | **partly** (URLs) |
| `parcels.py` | Status map, `normalize_parcel`, history, sort, filters — pure functions | **partly** (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` | Fetching, caching, event firing | mostly not |
| `config_flow.py` | Setup + options flow | **partly** (code validation) |
| `sensor.py` / `button.py` / `calendar.py` | Entities | no |
| `device_trigger.py` | Device triggers | no |
| `diagnostics.py` | Redacted diagnostics | **partly** (`TO_REDACT`) |
| `services.py` | `track_parcel` / `untrack_parcel` (account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects: the part you rewrite
per carrier stays unit-testable without spinning up Home Assistant.

## Tests on Windows

`tests/conftest.py` carries two Windows-only shims (both no-ops elsewhere):
pytest-homeassistant-custom-component's `disable_socket` is neutralised
(Windows event loops need AF_INET socketpairs; the connect-time 127.0.0.1
allowlist stays), and HA's hardcoded aiohttp `AsyncResolver` is swapped for
`ThreadedResolver` (aiodns refuses the Proactor loop). Do not remove them
"because CI passes" — CI is Linux, development happens on Windows.

## Docs and README

- The README stays **lean and installer-first** (suite house style): no
  per-entity `## Buttons` / `## Calendar` sections; the device-trigger option
  is one sentence folded into **Events**. This file documents everything else.
- **A code change updates the docs in the same commit** where behaviour
  changes — README, this file, and `docs/`.
- `docs/api/` is gitignored: reverse-engineering notes stay local.

## Workflow, commits, releases

See `ha-parcel-integrations/.github/CONVENTIONS.md` for the shared rules
(single-line commit messages, no `v` prefix on tags, semver, maintainer-only
merges, user-facing release notes). Not repeated here.

## Running tests

```
python -m pytest tests/ --cov=custom_components.cainiao
```

Coverage must stay **above 95%** (the silver `test-coverage` rule). Run before
committing.
