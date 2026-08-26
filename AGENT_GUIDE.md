# Telegram Rates Bot — AI Agent Guide

## Purpose

This private Telegram bot and API-key-gated Mini App let users maintain a
personal watchlist of exchange/crypto pairs, retrieve rates from multiple
sources, and calculate with displayed rates. User-facing text is mostly
Mongolian; preserve it unless a copy change is explicitly requested.

## Runtime flow

```text
main.py
  -> imports provider modules so decorators register them
  -> builds the python-telegram-bot application
  -> registers handlers from bot/handlers.py
  -> polls Telegram

api/app.py
  -> authenticates through api/auth.py
  -> exposes structured rates, subscriptions, calculator, and sharing
  -> serves the production React build from web/dist

web/src/App.tsx
  -> renders the Mini App/browser interface
  -> invokes native prepared-message sharing inside Telegram

Telegram command/button
  -> bot/handlers.py
  -> db/supabase_client.py (access, watchlist, cache)
  -> providers/base.py (registry + cache-aware retrieval)
  -> providers/<source>.py (live API/scraper fetch)
```

## Key files

| File | Responsibility |
| --- | --- |
| `main.py` | Starts the bot and imports registered providers. |
| `config.py` | Reads environment variables and cache TTL. |
| `bot/handlers.py` | Commands, callbacks, sharing, formulas, calculator. |
| `bot/keyboards.py` | Provider/pair selection and action buttons. |
| `db/supabase_client.py` | Supabase CRUD plus two-level rate cache. |
| `providers/base.py` | Provider class contract, registry, and `get_rate()`. |
| `providers/*.py` | Individual external rate sources. |
| `services/rates.py` | Structured snapshots, formulas, and share renderer. |
| `services/calculator.py` | Safe shared calculator evaluator. |
| `api/app.py` | Authenticated HTTP API and production SPA host. |
| `api/auth.py` | Mini App validation, sessions, and Telegram OIDC. |
| `web/` | React/TypeScript Mini App and browser UI. |
| `schema.sql` | Required Supabase database schema. |

## Access and stored data

The web app requires `APP_API_KEY` before it accepts Telegram Mini App or OIDC
identity data. The API key is checked only at login; authenticated sessions and
short-lived access tokens carry the resulting identity. The Telegram bot still
uses its separate Supabase `whitelist` table and hidden commands
`/wl_add <id>`, `/wl_remove <id>`, `/wl_list`.

Supabase tables:

- `users`: Telegram ID, username, creation time.
- `user_subscriptions`: user watchlist entries `(provider, symbol)`.
- `whitelist`: permitted Telegram bot IDs (the web app does not consult it).
- `cached_rates`: cached payload by `(provider, symbol)`.
- `share_bundles`: short-lived owner-bound browser sharing state.

## User behavior

- `/start`: checks access, creates the user record if needed, shows help and a
  calculator reply keyboard.
- `/add`: provider menu -> pair menu -> saves a subscription.
- `/remove`: uses the same menu; selected entries are deleted.
- `/list`: shows watchlist entries grouped by provider.
- `/clear`: deletes all of the current user’s subscriptions.
- `/rates` and `/oyuns`: retrieve and display every watched rate.
- `/calc`: starts the numeric calculator without displaying rates.

The server-to-server agent API can fetch one pair with `POST /api/agent/rate`.
For MongolBank, it accepts every uppercase `XXX/MNT` pair and returns `not
found` only when the official feed does not publish that currency. It is not
limited to the pair menu or a user subscription.

To fetch every pair exposed by every registered provider, every currency
currently published by MongolBank, and all enabled formula results, use
`GET /api/agent/rates` with `Authorization: Bearer $AGENT_RATES_API_KEY`.
Append `?force_refresh=true` to bypass provider caches. The agent should match
normal rates by `source` and `pair`, and formula rates by `kind: "calculated"`
and their `pair` (formula title). For example:

```bash
curl -H "Authorization: Bearer $AGENT_RATES_API_KEY" \
  "$APP_BASE_URL/api/agent/rates"
```

An agent integration must not maintain an enum of MongolBank currency pairs.
It should read the returned snapshots, then use `POST /api/agent/rate` with a
requested `XXX/MNT` pair only when it needs an individual refresh.

The all-rates response is deadline-bounded and may include `partial: true` and
provider-specific `warnings`. Agents must still consume entries whose `status`
is `fresh` or `stale`; one unavailable provider must not be presented as a
total exchange-rate service outage. For a specific user request, prefer
`POST /api/agent/rate` instead of loading the full catalog.

Pair-menu callback formats are part of the protocol:

```text
prov:<provider>
add:<provider>:<symbol>
del:<provider>:<symbol>
back:providers
```

Update both `bot/keyboards.py` and `callback_router()` if changing them.

## Rate retrieval, refresh, and sharing

`/rates` groups subscriptions by provider and fetches all rates concurrently
with `asyncio.to_thread()`. Each provider display line is sent as a separate
Telegram message. That is intentional: the calculator can then identify a
single rate from a replied-to message.

Each rate message has:

- Refresh: `upd:<provider>:<symbol>:<line_index>`. It calls `fetch()` directly,
  bypassing normal cache reads, then writes the fresh result into cache.
- Share: opens Telegram inline mode; the inline handler rebuilds the requested
  rate for the target chat.
- Menu: re-sends the command menu.

## Calculated rates

Calculated formulas are global rows in `calculated_formulas`. The schema seeds
the following defaults, and API-key-authenticated users can add, edit, reorder, disable,
or remove formulas in the Mini App. The bot fetches and displays these formula
rates as part of `/rates`:

```text
ДЕЛЬКРАДО = MongolBank RUB/MNT × 1.005
ТРИКУЭТРА = (TDBM non-cash USD/MNT sell ÷ CBR USD/RUB) × 1.01
RUB БЭЛЭН = lowest Binance P2P USDT/MNT offer ÷ Rapira USDT/RUB buy
```

Formula message IDs use stable database IDs, for example `_f:delcrado`.
Legacy numeric IDs such as `_f:0` remain readable on old messages. Refreshing
one regenerates the formula section and updates that formula’s displayed
message.

## Interactive calculator

`handle_message()` keeps per-user calculator state in `ctx.user_data`.

- Reply to a bot rate message with an operator, e.g. `/`, to begin.
- Reply to another bot rate with `=` (or `+=`, `/=`, etc.) to insert that rate
  as the next operand and evaluate.
- Plain numeric input can continue an active expression.
- `+`, `-`, `*`, `/` use normal precedence.
- Percent input such as `+0.5%` applies to the current subtotal.
- `Цуцлах`, `cancel`, `c`, or `х` cancels the calculation.

Provider display values should remain wrapped in backticks before conversion to
Telegram HTML `<code>` tags. `_extract_code_values()` relies on code entities to
extract a rate accurately.

## Group and inline calculator

In a group, a whitelisted user can mention the bot with an expression, for
example `@botname CBR:USD/RUB / 2`. The same expression works in inline mode:
typing `@botname CBR:USD/RUB / 2` shows the result before it is sent. Rate
operands must be in that user's saved shortlist and use
`Provider:PAIR[:field]`. A field is required when a rate has multiple values,
for example `TDBM:USD/MNT:noncash_sell`.

An empty group or inline mention returns calculator guidance or no result; it
does not display a saved-rate or formula shortlist. A non-empty mention shows
only the calculation result.

## Provider contract and cache

Every provider must:

1. Subclass `BaseProvider`.
2. Define stable `NAME` and `PAIRS` values.
3. Implement `fetch(symbol)` for live data.
4. Return at least `{"lines": ["display-ready line"]}`.

`BaseProvider.get_rate()` serves a shared snapshot until the provider's policy
is due, then refreshes it under a short Supabase lease. Binance and Rapira use
five minutes; XE and Profinance use one hour; bank and central-bank feeds use
the next configurable daily Ulaanbaatar refresh window (09:00 by default).
The dedicated `refresher` Compose service updates only unique subscription and
enabled-formula dependencies. User refreshes remain cache-aware; only the
authenticated agent API can explicitly force an upstream refresh.

Registered through `providers/registry.py`: `CBR`, `XE`, `Binance`, `Rapira`,
`Profinance`, `BOC`, and all 15 institutions exposed by
`btseee/mongolian-bank-exchange-rate`, including `TDBM`.

The 15 normalized Mongolian providers require `MONGOLIAN_BANK_API_URL` to point
to a running instance of that upstream API.

`providers/grx.py` exists but is intentionally not imported by the shared
registry, so GRX is not exposed.

## Change-safety notes

- Providers use synchronous `requests`; invoke them with `asyncio.to_thread()`
  from async handlers so Telegram’s event loop stays responsive.
- Provider names and symbols are persisted in existing watchlists and cache
  rows. Renaming either requires a data migration.
- Callback IDs use colons as separators; do not introduce ambiguous colons into
  provider names or symbols.
- External sites can fail or change markup. Return a displayable error payload
  instead of crashing a command on routine provider failures.
- Telegram output uses `ParseMode.HTML`; escape untrusted content before adding
  it to HTML messages.
- Timestamps in handlers explicitly use Ulaanbaatar time (UTC+8).
- Adding a provider requires both its module and an import in
  `providers/registry.py`.

## Configuration and startup

Required environment variables:

```text
TELEGRAM_BOT_TOKEN
SUPABASE_URL
SUPABASE_KEY
```

Optional: `CACHE_TTL` (defaults to `300`). Apply `schema.sql` before use.

The web/API surface additionally uses `APP_BASE_URL`, `SESSION_SECRET`,
`TELEGRAM_BOT_USERNAME`, `TELEGRAM_APP_SHORT_NAME`, and
`TELEGRAM_OIDC_CLIENT_ID`/`TELEGRAM_OIDC_CLIENT_SECRET`. See `.env.example`.

```bash
python main.py
```

Startup uses `run_polling(drop_pending_updates=True)`, so Telegram updates sent
while the bot was offline are deliberately discarded.
