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

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/market-sentinel --help
.venv/bin/market-sentinel push-test
```

The last command is safe: without `--send`, it sends nothing, reads no credentials
and exits **2**. The installed entry point also works as
`.venv/bin/python -m market_sentinel`.

## Pushover transport proof — implemented

This slice sends only this fixed test message:

> **Market Sentinel — Test**
>
> Push transport verification. No market signal or trading action.

It posts once to the fixed HTTPS Pushover endpoint with a 10-second network
timeout, normal certificate validation, no redirects and no ambient HTTP proxies.
It checks both HTTP 200 and integer JSON `status: 1`. It never prints credentials,
raw response bodies or raw transport errors. There are no automatic retries:
a timeout can occur after the provider accepted the notification.

Exit **0** means API acceptance only; exit **1** means request failure or unknown
acceptance; exit **2** means command misuse or the missing `--send` flag.
Neither a successful exit nor a provider response confirms phone delivery.

### Operator setup — do this yourself; do not share secrets

1. Install the [Pushover iPhone app](https://pushover.net/clients), create/sign into
   your own Pushover account, and enable iPhone notifications. The trial can be
   used before deciding whether to purchase the individual iOS license. This code
   creates no account and purchases nothing.
2. On your [Pushover dashboard](https://pushover.net/), find your **User Key**.
3. Use [Create an Application/API Token](https://pushover.net/apps/build) to register
   your own application named **Market Sentinel**. Choose the appropriate script/
   application type; obtain its **API Token/Key**. No market-data or brokerage
   account is involved. Never reuse example tokens from documentation.
4. Prefer **Keychain Access** on the Mac. In your login keychain, create two
   password items (File → New Password Item):

   | Keychain Item Name (service) | Account | Password |
   |---|---|---|
   | `market-sentinel.pushover` | `application-token` | Your application token |
   | `market-sentinel.pushover` | `user-key` | Your User Key |

   Enter values directly into Keychain Access, never into repository files or
   shell commands. The client reads them through `/usr/bin/security` only when
   `push-test --send` is explicitly invoked. macOS may ask you to allow Keychain
   access; a locked/missing item fails safely. Retrieval is limited to 15 seconds
   per item, so complete any access prompt promptly or run again after resolving
   it. Environment overrides take precedence and must supply both values.
5. **Stop until the operator explicitly authorizes one live transport test.**
   Provider setup alone is not permission for a coding actor to send a message.

After that authorization, the operator can run exactly once:

```sh
.venv/bin/market-sentinel push-test --send
```

Independently verify that the exact test appears on the locked iPhone, with the
app not foregrounded, and confirm receipt to the engineer. Check iOS notification
permissions and Focus settings if the API accepts but no notification appears.
Do not describe this as a market signal or an operational daily monitor.

### Initial environment handoff alternative (interactive zsh)

If Keychain has not been configured, hidden terminal input is acceptable. Never
type the actual values as command arguments or save them in an `.env` file inside
the checkout. The following subshell keeps values out of shell history, disables
tracing and drops its environment on exit. **It sends a real request: use only
after explicit authorization.**

```sh
(
  set +x
  read -rs 'PUSHOVER_APP_TOKEN?Pushover application token (hidden): '
  printf '\n'
  read -rs 'PUSHOVER_USER_KEY?Pushover user key (hidden): '
  printf '\n'
  export PUSHOVER_APP_TOKEN PUSHOVER_USER_KEY
  .venv/bin/market-sentinel push-test --send
)
```

Environment values are temporarily available to the child process and potentially
privileged local inspection. Use Keychain for ongoing operation. No command accepts
credentials as arguments, and argument errors do not echo supplied arguments.

### Failure handling and maintenance

- Rejected credentials/request: check the dashboard, token, User Key and active
  device. Fix setup before another authorized attempt; repeated requests do not
  repair authentication.
- Quota: wait for reset or investigate usage; do not loop. Network/TLS/server
  failure or timeout: acceptance may be unknown. Check the phone before authorizing
  another test; duplicate delivery remains possible after an ambiguous failure.
- Revoke/replace compromised credentials through the provider, update Keychain,
  unset stale environment overrides and authorize a fresh test. Never put old or
  new values in a report. Error output intentionally omits raw provider diagnostics.
- API acceptance, OS notification display and operator-confirmed receipt are
  separate observations. There is no receipt tracking or durable retry queue in
  this transport-only proof.

Tests mock HTTP and Keychain using synthetic credentials, including successful
request construction, rejected credentials, malformed/provider errors, timeout,
safe diagnostics, explicit send intent and CLI exit status. No live push is needed
for code-level completion. Future acceptance adds offline indicator fixtures,
TradingView comparison, synthetic crossings, independent identities, deduplication,
re-arming, missed-session recovery, all-symbol data validation, then scheduling.

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
