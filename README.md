# Cainiao Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-cainiao.svg)](https://github.com/ha-parcel-integrations/ha-cainiao/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

> ### ⚠️ Early release — the mapping is well-evidenced, not yet confirmed
>
> Everything works: parcels are polled, mapped, and published as sensors,
> events and a calendar. The field names come from Cainiao's published response
> schema and the status codes are cross-checked between two independently
> maintained trackers.
>
> What is missing is a **fully populated response captured from a real parcel**.
> Only the "unknown tracking number" response has been verified first-hand. So
> if something reads oddly, it is worth reporting rather than assuming it is
> your parcel — see [How you can help](#how-you-can-help).

A custom Home Assistant integration that tracks cross-border parcels through [Cainiao](https://global.cainiao.com) — Alibaba's tracking layer for AliExpress, Temu, Shein and similar shops. No account is needed: you enter the tracking number yourself, just like on Cainiao's own tracking page.

**Why this and not your national carrier's integration?** A parcel from China is invisible to PostNL, DHL or DPD until it reaches their network, often two weeks after you ordered. Cainiao sees it from the day it ships. Once a local carrier takes over the last leg, that carrier's integration takes over too — so the two complement each other rather than compete.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [How you can help](#how-you-can-help)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of parcels by tracking number — no account needed
- Per-parcel sensor with the canonical status (`in_transit` / `out_for_delivery` / `delivered` / …), Cainiao's own status text and a tracking deep-link
- Summary sensors: incoming parcels, recently delivered parcels
- `cainiao.track_parcel` / `cainiao.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.7 or newer
- A tracking number from your AliExpress, Temu or similar order — usually
  starting with `LP`. No account needed.

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-cainiao` as an **Integration**.
3. Install **Cainiao** and restart Home Assistant.

### Manual

Copy `custom_components/cainiao` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Cainiao**. There is nothing to fill in: the hub is created immediately (Cainiao tracking needs no account or postal code).

Then add parcels via the integration's **Configure** dialog, the [`cainiao.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking number is in your order details or the shipping confirmation mail.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking numbers. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

## Removal

Standard HA removal applies: **Settings → Devices & Services → Cainiao → ⋮ → Delete**. Nothing is stored on Cainiao's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.cainiao_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.cainiao_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.cainiao_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.cainiao_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.cainiao_last_successful_update` | Diagnostic: when Cainiao was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `in_transit` | Moving through the network, including customs |
| `out_for_delivery` | With the courier for the final delivery |
| `at_pickup_point` | Waiting for you at a pickup location |
| `delivered` | Delivered |
| `returning` | Going back to the sender |
| `problem` | Cainiao reports an exception |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

`unknown` is normal for the first days after ordering — a cross-border parcel
often has no scans at all until it leaves the origin country.

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Cainiao device):

| Event | When |
|---|---|
| `cainiao_parcel_registered` | A new parcel appears in the active list |
| `cainiao_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `cainiao_parcel_delivered` | A parcel is delivered |
| `cainiao_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `cainiao.track_parcel` | `tracking_code` | Start tracking a parcel |
| `cainiao.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.cainiao: debug
```

## How you can help

Cainiao describes each scan with an **action code** — `LH_DEPART`,
`GTMS_SIGNED`, and so on. The integration maps 31 of them; the list is
cross-checked against two other trackers, but it is certainly not complete.

An unrecognised code makes the parcel report `unknown` rather than guessing,
and writes one line to your log:

```
Unrecognised Cainiao action code — help us map it. Open an issue and paste this line: …
  actionCode=SOME_NEW_CODE → reported as 'unknown'
```

[Opening that issue](https://github.com/ha-parcel-integrations/ha-cainiao/issues/new?template=unrecognised_status.yml)
with the logged line is all it takes — the code alone is enough, and it says
nothing about you or your parcel.

Equally useful: if a parcel shows a status that feels *wrong* rather than
unknown — say it claims delivered while it is still at a pickup point — that is
worth an issue too. Those are the mappings we have the least evidence for.

## Troubleshooting

- **A parcel shows `unknown`** — usually just means Cainiao has no scans for it yet, which is normal for the first days after ordering. It picks up automatically. If it stays `unknown` after the parcel clearly moved, the status token is one we do not map yet — see the next point.
- **A status logs "Unrecognised Cainiao status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-cainiao/issues/new) with the logged line. The status vocabulary is still being mapped from real parcels, so these reports are how it gets complete.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as Cainiao's own tracking page. It is not affiliated with, endorsed by, or supported by Cainiao or Alibaba.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
