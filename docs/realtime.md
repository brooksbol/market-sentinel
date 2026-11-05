# Realtime attention candidate — November 5, 2026

Bounded engineering commissioned by the Principal. Not installed, activated or
production-ready. No live push verification or cloud deployment is authorized.
The XOM/CVX crossings described in the assignment are operator observations;
this increment does not independently certify their occurrence or timing.

## Recovery and scope

Discovery: `/Users/bollich/kiro/market-sentinel`, clean local main at `9004b93`.
Initial remote main: `ead051f9446fa9977abd99d36d16aff3037565de`.
The installed history-viewer precedent lives on published branch
`codex/local-report-history`, tip `498bdd60a3f222a00683a538c5062eed88a96816`.
This candidate extends that branch in a separate worktree; it does not edit the
installed checkout, environment, entry point or operational state. Remote main
subsequently advanced to `a41c91ddfddcf8022251b2bdece1e27851bff30e` with unrelated
experiment documentation, preserved during integration.

Governing sources: the Principal's realtime assignment and repository `AGENTS.md`.
Working precedents: `stochastic.py` (TA-Lib 14/3/3), `tradier.py` (bounded safe
GET), `scheduled_report.py` (calendar validation), `pushover.py` (transport and
message limits), and `report_history.py` (loopback browser investigation).
No Wheelwright runtime, accounts, options, new indicators, frontend framework,
paid subscription or cloud resources are added.

## Phase 1: actual acquisition evidence

Official sources checked November 5, 2026:

- [Market data](https://docs.tradier.com/docs/market-data): consolidated real-time
  production US equity data for entitled Tradier users; sandbox delayed 15 minutes.
- [Quotes](https://docs.tradier.com/reference/brokerage-api-markets-get-quotes):
  multi-symbol quotes, OHLC and last-trade epoch timestamp (example milliseconds).
- [Time and sales](https://docs.tradier.com/market-data/get-time-and-sales):
  `1min`, `5min`, `15min`, or tick; explicit `session_filter=open` excludes pre/post
  market. Minute retention documented as 20 days for open-session data. Default
  `all` and default tick are unsuitable here.
- [Example timestamps](https://docs.tradier.com/code-examples/get-time-and-sales-data):
  minute `time` in exchange wall time paired with Unix epoch seconds. This adapter
  requires their agreement in America/New_York rather than trusting naive time.
- [History](https://docs.tradier.com/market-data/get-historical-pricing): documented
  split-adjusted, not dividend-adjusted. Existing accepted mixed-close anomalies
  remain warnings, with prices unchanged. Intraday aggregation is current spot
  OHLC; no dividend adjustment or repair is applied. No independent corporate
  action reconciliation or identical-provider-basis guarantee is claimed.
- [Rate limits](https://docs.tradier.com/overview/rate-limits): production markets
  120 requests/minute/token; sandbox 60. Quota can be HTTP 400 `Quota Violation`,
  alongside the defensive 429 handling already implemented. Limits are shared
  with other uses of the same token; this candidate does not exhaustively measure
  other clients' consumption or add automatic quota retries.
- [FAQ](https://docs.tradier.com/overview/faq) and
  [authentication](https://docs.tradier.com/docs/authentication): personal-use API;
  redistribution requires Partner arrangements, personal tokens have broad access.
  No new token/scopes or account endpoint is used. A private cloud runner remains
  personal use in intent; hosted display, redistribution, exchange agreements and
  the operator's exact hosting rights must be checked before cloud deployment.
  Public documentation is not verification of every signed entitlement/term.

A bounded production probe made **23 market-data GETs** using the existing token:
1 batched quote request, 21 minute-series requests (XOM/CVX initial pair, then all
19), and 1 current-month calendar. No account/order endpoints were used.
At 19:21:25–26 UTC all 19 quote trade times were approximately 1–44 seconds old.
The XOM/CVX minute series began 09:30 ET and included a developing 14:21 minute.
The all-symbol sweep at 19:22:18–29 UTC took **12.159 seconds** and returned HTTP
200, positive in-range OHLC and fresh current-minute timestamps for all 19.
Six symbols (CLX, ADM, TGT, SWK, SHW, TROW) had **seven missing minute intervals**
(two CLX; one each elsewhere). This is not proof of missing trades versus missing
provider records. No zero-trade assumption or candle filling is permissible.
The calendar reported 09:30–16:00 Eastern on November 5. Responses exposed quota
allowance 120 where present. This verifies access on this occasion, not a freshness
SLA, full entitlement audit, or continuous all-symbol usable coverage.

Smallest selected acquisition: sequential polling of regular-session minute OHLC,
not streaming. A quote-only developing candle was rejected because the inspected
quote contract does not establish an independently timestamped regular-session
OHLC snapshot. Strict minute continuity is required; the six sparse series would
be degraded and **would not generate signals** in this sweep. Restoring coverage
requires complete provider minute responses or separately verified semantics for
sparse intervals/an alternative complete candle feed. This remains a coverage
limitation, not permission to fill gaps. No alternative provider was purchased or
connected; Tradier's current access supports the candidate with explicit partial
coverage, not a promise of continuously usable observations for all 19.

## Cadence, sessions, latency and failures

The foreground loop uses a **provisional 180-second pause after each sweep**;
this is an engineering default, not a Principal-ratified operational threshold.
At most ten calendar, 19 history and 19 minute GETs on a usual cold start; warm
sweeps use 19 minute GETs. Histories/calendars cache in process for the Eastern
calendar day; restarts reacquire them. Acquisition stops starting new requests
after 90 seconds (an outstanding bounded 15-second GET can finish later).
Completed-close follow-up may add up to 19 history GETs within remaining sweep
budget. There is no tick-level responsiveness, catch-up burst, streaming session,
network retry loop, or historical reconstruction of missed intraday alerts.

Current minute excluded: aggregation ends at the final completed minute, normally
0–60 seconds behind wall time plus publication delay. Freshness is age from the
last included minute **end**, limited to 180 seconds at acquisition and again
before detection/delivery. It is not a last-trade timestamp or guarantee of a
trade exactly at that boundary. With the observed 12.2-second acquisition sweep,
a crossing that persists until sampling might be detected approximately within
one loop interval plus a minute of bar formation, acquisition and publication
latency; roughly 3–5 minutes is an estimate, **not a measured end-to-end SLA**.
Push transport adds its request latency (10-second timeout); phone latency and
receipt remain unverified. Transient crossings between polls can be missed.

Calendar sessions, holidays, early closes and ET offsets reuse the established
complete-month validator in new portable `sessions.py`. No weekday fallback.
Mountain and DST conversion use `ZoneInfo`. Before opening/after closing no
intraday evaluation; a sweep that crosses close cannot issue delayed signals.
Startup after opening qualifies first sightings; opening incomplete minutes are
unavailable. Network/auth/quota errors, sparse/malformed/out-of-range current OHLC,
missing historical calendar sessions, warm-up and stale data degrade coverage.
Provider or credential exceptions are sanitized. No missing number becomes zero.
The dashboard remains readable during provider failures. Retry waits until a
subsequent explicit sweep/foreground cadence; auth/quota stops the current batch.

## Calculation and event policy

Completed daily bars remain unchanged and strictly before the current session.
Append exactly one provisional candle: first regular-minute open, maximum high,
minimum low, and final completed-minute close. TA-Lib STOCH uses fast K 14,
slow K SMA3 and slow D SMA3, unchanged validity masks and full precision. The
completed baseline is separately calculated and retained. Raw K and D never
trigger crossings. Full-precision comparison is previous K >=20, current K <20.
The current provisional candle cannot appear in historical input twice.

- Prior close below20 and first reading still below20: `already_oversold`; no push.
- Prior close >=20 and first reading below20: first observed below since completed
  close, exact crossing time unknown. One qualified first-sighting alert is allowed.
- Adjacent usable observations: entered/recovered transitions retained with both
  values, observation interval ends and actual detection time. No exact tick claim.
- Known outage or observation separation >360 seconds: transition retained as
  `observation_gap`; downward attention suppressed, because the interval is unknown.
- Repeated downward transitions remain events, but only the **first downward event
  per symbol/session** can reserve notification intent. Re-arming does not send
  additional pushes. Initial sightings, preview-only and gap-suppressed downward
  events consume this conservative budget. Switching to send mode does not replay.
- A provisional event that disappears is never rewritten. Separate post-close
  evidence records first usable completed K/D, whether still oversold, and the
  separately calculated daily crossing. Later provider revisions are possible;
  this is not a guarantee of irreversible finality. Follow-up failures remain
  explicit and are revisited on later sweeps. It requires the monitor to run
  after close or on a later invocation.

## Durable state and delivery

Default independent state: `$XDG_STATE_HOME/market-sentinel/intraday/state.sqlite3`,
otherwise `~/.local/state/market-sentinel/intraday/state.sqlite3`. An explicit
`--state` path may target a dedicated private directory. No working-directory,
launchd, browser or Keychain dependency in calculation/state/monitor orchestration.
Tradier and Pushover secret loaders already accept injected environment secrets;
Keychain remains an optional local adapter.

SQLite stores content-addressed source bars/calendar evidence, full-precision
observations, per-symbol continuity status, immutable transition events and policy
suppression, notification intent/outcome, immutable first completed follow-up,
current status and append-only sweep/failure records. Event identities start
`intraday:` and never reuse completed-report identities. A write transaction
serializes event/intent reservation across competing writers, committed with
SQLite FULL synchronization **before** HTTP. No historical events are overwritten
by reversals or completed results. Preserve and back up this ledger: deletion,
reset or copying an old backup can duplicate alerts. No pruning policy yet;
retained minute payloads mean storage grows with runtime and needs measurement
before activation. Preview data uses the same conservative ledger semantics.

No `--send`: generated evidence/preview only, no Pushover credentials or HTTP.
With separately authorized activation and `--send`, event formatting reuses the
existing transport and 1024-character body / 250-character title preflight.
Alerts show symbol, previous/current K, minute-close price, both observation
identities, detection time, provisional status and lack of close confirmation.
`intent_uncertain` is durable before transport. `api_accepted` means API acceptance
only; any failure is `acceptance_unknown`. An interrupted intent is also uncertain.
Neither is retried automatically. Phone receipt is never asserted or tracked.

## Investigation and engineering commands

After a separately authorized future installation, ordinary operator commands:

```
sentinel                 # existing report history, unchanged default
sentinel --realtime      # all 19; read-only view, refresh every 15 seconds
sentinel --realtime XOM  # focused baseline, current candle and event evidence
```

The viewer does **not** activate acquisition or notifications. It reads the monitor's
ledger, prioritizes recent downward events, shows provisional K/D and price, state,
completed K/D, changes, freshness, coverage, last successful updates and recent
transitions. Focus exposes full precision and provenance. All 19 rows remain
visible even without data. Stale retained values are explicitly labeled; they
are evidence, not fresh signals. The existing history server's loopback-only
binding, host/origin checks, escaped rendering and GET-only policy are reused.
It must not be exposed publicly or used as an authenticated cloud dashboard.

Engineering source invocation from this isolated candidate, without installation:

```
PYTHONPATH=src /path/to/existing/python -m unittest discover -s tests -q
PYTHONPATH=src /path/to/existing/python -m market_sentinel.report_history --realtime --state /private/synthetic/state.sqlite3
```

Monitor entry `python -m market_sentinel.realtime` makes one live production-data
sweep when explicitly invoked; `--loop` runs foreground. Both default to preview.
`--send` enables real event transport and requires separate Principal activation
authorization. These commands are documented for review, **not run live here**.
No scheduler, daemon, credential change, installation, deployment, actual event
notification or trade occurred in this assignment.

## Cloud portability and remaining acceptance

The core and SQLite storage seam are portable Python; only the existing daily
report adapter imports macOS-specific `fcntl`/launchd machinery. Shared calendar
validation has no such import. Cloud requires managed secret injection, a durable
single-writer SQLite volume or another transaction-capable state implementation,
cloud invocation/scheduling, clock/latency and shutdown validation, storage/backup
and retention sizing, failure escalation, and an authenticated private display
adapter. Ephemeral SQLite is unsuitable. Distributed runners require equivalent
atomic reservation, not independent state files. No migration is implemented.

Operational decisions/verification before activation: accept cadence/freshness
and once-per-session/first-sighting policy; resolve acceptable sparse-series
coverage; verify signed data/hosting rights, sustained provider latency and token
quota sharing; measure state growth; verify a separately authorized notification
and phone receipt; arrange durable runtime, retention, failure visibility and
installation rollback. Offline tests and independent engineering review establish
candidate correctness only; they do not establish production readiness or
Principal operator acceptance.
