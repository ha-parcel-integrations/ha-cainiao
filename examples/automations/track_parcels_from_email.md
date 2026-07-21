# Automatic parcel tracking from e-mail (IMAP → Cainiao)

Companion guide for [`track_parcels_from_email.yaml`](track_parcels_from_email.yaml): watch your mailbox(es) for shipping e-mails, extract the Cainiao tracking code, and register it with `cainiao.track_parcel` — fully automatic, no extra custom component required.

Cainiao is a **code-based** carrier: it has no account inbox, so every parcel must be registered by its tracking code before the integration can follow it. This recipe automates exactly that step.

**How it works, in one line:** the core [IMAP integration](https://www.home-assistant.io/integrations/imap/) fires an `imap_content` event for every new e-mail (including the body); the automation extracts the tracking code — a cheap regex first, an optional AI fallback for everything else — and calls `cainiao.track_parcel`.

```
new e-mail ──imap_content──▶ automation ──▶ regex match? ──▶ cainiao.track_parcel
                                     │
                                     └──▶ no match, but looks like a shipping mail
                                          ──▶ ai_task.generate_data (optional)
                                              ──▶ tracking code
```

## Prerequisites

- This integration, with the `cainiao.track_parcel` action available (field `tracking_code`).
- The core **IMAP** integration (ships with Home Assistant, no HACS needed).
- *(Optional but recommended)* an **AI Task** entity (e.g. Anthropic/Claude, Google, OpenAI) for the fallback path. Without it, simply delete the `else:` block — the regex path works standalone.

## Step 1 — IMAP entries

Add **Settings → Devices & services → Add integration → IMAP** for every account you want to watch:

| Field | Value |
|---|---|
| Server | `imap.gmail.com` (Gmail) — mind the hostname, it is **not** `imap.google.com` |
| Port | `993` |
| Username | your address |
| Password | see the Gmail note below |
| Charset | `utf-8` |
| Folder | `INBOX` (or a label/subfolder — see below) |

Then open the entry's **Configure** (options) and set:

- **Message data to include in the event**: enable **text** (the automation needs the body!)
- **Max message size**: raise it to `30000` — carrier mails are long and the default cuts them off before the tracking code appears.
- Leave *search* on `UnSeen UnDeleted` and *push* enabled (IMAP IDLE → events arrive within seconds).

**Multiple mailboxes / accounts:** each IMAP entry is one account × folder combination. Add the same account again with a different folder to watch labels (Gmail labels appear as IMAP folders). All entries fire the *same* `imap_content` event, so **one automation covers all of them**.

**Gmail note:** since May 2025 Google blocks plain-password IMAP logins ("less secure apps"). Use an **app password** instead (requires 2-step verification): <https://myaccount.google.com/apppasswords>.

## Step 2 — the automation

Paste [`track_parcels_from_email.yaml`](track_parcels_from_email.yaml) and adapt the notify action, the keyword list and the AI entity to your setup.

### Tracking-code formats

The regex matches Cainiao's own label format — `LP` followed by 12 to 18 digits:

```
(?<![0-9A-Za-z])LP[0-9]{12,18}(?![0-9A-Za-z])
```

That is deliberately narrower than what the integration itself accepts (`^[A-Z0-9]{8,30}$`), because matching *that* against prose would hit every order number in the mail.

**Cainiao answers for more than LP numbers.** It is a tracking layer rather than a carrier, so it also responds to UPU S10 numbers — two letters, nine digits, a two-letter country code, e.g. `RS123456789NL` — and to some local carriers' own numbers. Adding S10 to the alternation is a one-line change:

```
(?<![0-9A-Za-z])(?:LP[0-9]{12,18}|[A-Z]{2}[0-9]{9}[A-Z]{2})(?![0-9A-Za-z])
```

It is left out by default because S10 numbers are exactly the ones a *national* carrier integration is likely to be tracking already — you would end up with the same physical parcel on two dashboards. Add it if you want the cross-border leg visible before the local carrier picks the parcel up, and accept the duplicate.

There is no universal catalogue to look this up in, incidentally. The most complete open dataset of tracking-number formats, [`jkeen/tracking_number_data`](https://github.com/jkeen/tracking_number_data), covers UPS, FedEx, USPS, DHL, DPD, Canada Post, Amazon and the S10 standard used by 160+ national posts — but carries nothing for Cainiao, because `LP` numbers are a private format rather than a standardised one. And format alone can never fully identify a carrier: several use identical shapes.

### Design notes

- **Regex first, AI second.** Mails straight from the carrier match the regex and never touch the AI. The AI fallback earns its keep on the messy cases: forwarded mails, webshop confirmations, unfamiliar layouts.
- **Duplicates are harmless:** calling `track_parcel` twice for the same code is a no-op, and the `initial` condition already suppresses re-triggers of the same message.
- **`mode: queued`** so a burst of mails (mailbox sync) is processed one by one instead of being dropped.

## Pitfalls we hit so you don't have to

1. **Jinja eats backslashes in string literals.** A template stored as `regex_findall('\bLP…')` silently becomes a **backspace character** (`\b` is a string escape), so the regex never matches — no error anywhere. That's why the pattern is backslash-free: `(?<![0-9A-Za-z])` lookarounds instead of `\b`, `[0-9]` instead of `\d`. Copy that style if you extend the pattern.
2. **The `initial` event flag means the opposite of what you might expect.** In the IMAP integration `initial: true` = *first time this message is seen* (new mail); `false` = a duplicate trigger of the same message. So the condition must **require** `initial`, not exclude it.
3. **Raise the max message size.** With the default the body is truncated before the tracking code appears in most carrier mails. `30000` is plenty.
4. **Enable "text" in the event options.** Without it the event has headers only and there is nothing to extract.
5. **Gmail = app password.** Plain passwords stopped working on Google IMAP in May 2025; app passwords (with 2FA) are the supported route. And the host is `imap.gmail.com`.

## Testing without waiting for a real parcel

Fire a fake event and watch the automation trace (Settings → Automations → your automation → Traces):

```bash
curl -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
  http://YOUR_HA:8123/api/events/imap_content \
  -d '{"sender":"noreply@cainiaoshipping.com","subject":"Your parcel is on its way",
       "text":"Tracking code: LP00123456789012","initial":true,"folder":"INBOX","username":"test"}'
```

Then `cainiao.untrack_parcel` the test code afterwards. For a full end-to-end test, forward a real shipping mail to the watched mailbox — it must arrive **unread**.
