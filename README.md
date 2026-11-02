# Market Sentinel

An independent utility for monitoring technical-indicator crossings on 19 fixed
equities and notifying one operator. Notifications support manual review; they
never authorize or execute a trade.

## Current scope

Repository foundation and a bounded Pushover transport proof. The market monitor
is **not implemented**: no market-data connection, indicators, database, daily
receipt or installed scheduler exists. This project has no Wheelwright runtime,
deployment, credential or Product dependency.

## Environment and development

Target: macOS, a maintained Python **3.12 or later**, and an iPhone with Pushover.
Offline tests can run on other Python-supported operating systems. macOS Keychain
integration and the eventual launchd installation are macOS-specific.

Use a separately installed maintained Python, not an obsolete system Python:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e .
```

There are no third-party runtime or test dependencies. Packaging uses setuptools;
tests use Python's standard-library `unittest`. Routine verification must never
contact Pushover or the operator's Keychain.

## Intended monitor — requirements, not implemented

Keep scheduling, data acquisition, pure indicator calculations, crossing
detection, persistence and notification transport independently replaceable.
Implement two concrete indicators, not a general technical-analysis framework.

Fixed initial universe:

`CLX, O, CVX, NUE, ADM, MCD, IBM, XOM, CAT, TGT, SWK, SHW, WMT, PG, ABBV, APD, TROW, KO, PEP`

- **Stochastic(14,3,3):** raw close position in the rolling 14-session high/low
  range; three-period SMA for displayed %K; another three-period SMA for %D.
  Trigger on smoothed %K; %D is informational, not a crossover requirement.
- **Wilder RSI(14):** closing-price changes, initial 14-change arithmetic averages
  and recursive Wilder smoothing. Trigger on RSI itself.
- Both trigger only when the previous completed-session value is **>= 20** and
  the current completed-session value is **< 20**, using unrounded values.
  Re-arm independently per symbol and indicator after recovery to >= 20.
- Calculate and record both indicators; initially enable Stochastic notifications
  only. Higher expected event frequency is an operational-testing hypothesis,
  not evidence of better acquisition performance. RSI remains a separate
  acquisition-signal hypothesis. Any historical strategy study is a separate task.
- Resolve warm-up, zero-range/zero-gain-loss and missing-value behavior explicitly
  in offline fixtures. Validate against TradingView's regular 1D indicators with
  matching data and adjustment settings before operational acceptance.

**Data:** Alpaca Basic historical SIP daily OHLC is the candidate, subject to
authenticated coverage, entitlement, freshness and TradingView validation. Acquire
once for both indicators. Use only completed US equity sessions; handle holidays,
early closes, DST, missing/duplicate bars and revised history. Apply consistent
split adjustments to every OHLC field; choose dividend treatment explicitly.
Missing data is a failure, never evidence that no crossing occurred.

**State:** eventual local SQLite retains inputs/provenance, event identities,
per-symbol/indicator progress, run status, notification attempts and sanitized
provider responses. Event identity includes symbol, indicator/configuration,
threshold/direction and completed session date. Recover unprocessed sessions
chronologically; prevent ordinary duplicate alerts. Exactly-once event recording
does not imply exactly-once notification delivery.

**Daily receipt: “Nothing is something.”** Every completed trading session must
eventually have one accountable logical monitoring receipt, preferably sent as one
consolidated notification. A quiet success reports 19/19 evaluated, both crossing
counts, current data and no acquisition signals. A signal receipt lists new
crossings with symbol, indicator, prior/current values, close and original session
date, marked informational/manual review required. Failure reports incomplete or
stale evaluations and never claims successful zero signals. Retries/revisions
update the logical receipt while preserving history; exact-once push delivery is
not promised.

**Scheduling:** eventual macOS launchd invocation around 18:37 America/New_York,
with wake/startup catch-up. The monitor, not the scheduler, owns session selection,
calculation and persistence. Catch-up delay while the Mac is off is accepted.

## Security and operational boundaries

- The repository is public. Keep secrets, personal operating data, SQLite files,
  logs and local configuration **outside the checkout**. `.gitignore` is a guard,
  not a substitute for checking staged contents.
- Prefer macOS Keychain for credentials. Never paste secrets into chat, issues,
  pull requests, source, command history, logs or fixtures.
- No trading, brokerage integration, equity selection, portfolio optimization,
  dashboard, cloud deployment or GitHub Actions scheduling is commissioned.
- Do not create accounts, purchase services, send a live notification or install
  a scheduler without the corresponding operator authorization.
- Preserve the distinction between provider API acceptance and independent phone
  receipt confirmation. Transport failures must remain visible.

## Provider references

Verified November 1, 2026 (Mountain Time):

- [Pushover API](https://pushover.net/api): HTTPS POST, application token and user
  key; accepted requests return HTTP 200 and JSON `status: 1`.
- [Pushover pricing](https://pushover.net/pricing): 30-day trial, $4.99 one-time
  individual iOS license, no recurring individual subscription. No purchase is
  required or performed by this repository bootstrap.
- [Python support status](https://devguide.python.org/versions/): use a maintained
  runtime. Provider terms and prices may change.
