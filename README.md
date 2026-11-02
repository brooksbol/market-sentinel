# Market Sentinel

An independent utility for monitoring technical-indicator crossings on 19 fixed
equities and notifying one operator. Notifications support manual review; they
never authorize or execute a trade.

## Current scope

Market Sentinel is an **attention mechanism**: informational screening signals
prompt independent manual review, never execution or authoritative investment
recommendations. The Principal selected **Tradier** and accepts occasional extra
or missed screening signals from imperfect historical prices.

Implemented: standalone Pushover test transport, TA-Lib Stochastic(14,3,3), pure
crossing detection, and an explicitly invoked Tradier report for all 19 configured
symbols. Range inconsistencies produce structured warnings without price repair.
RSI, persistence, durable deduplication, daily notification receipts and scheduling
remain unimplemented. Indicator results are not connected to Pushover. This is
independent of Wheelwright's runtime, credentials and Product boundaries.

## Environment and development

Target: macOS, a maintained Python **3.12 or later**, and an iPhone with Pushover.
Offline tests can run on other Python-supported operating systems. macOS Keychain
integration and the eventual launchd installation are macOS-specific.

Use a separately installed maintained Python, not an obsolete system Python:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e .
```

Production indicator mathematics use **TA-Lib==0.8.3**, the maintained Python
binding to the open-source C library. This current release is pinned for deliberate,
tested upgrades. NumPy is installed through TA-Lib's own dependency metadata;
there is no duplicate direct NumPy requirement. Tests use standard-library
`unittest` plus the installed numerical dependency. Packaging uses setuptools.
Routine verification must never contact Pushover or the operator's Keychain.

Binary wheels bundle the C library. Verified here: Python **3.14.10**, macOS arm64,
TA-Lib Python/C **0.8.3**, NumPy **2.5.4**, installed without a compiler, Homebrew
TA-Lib or a separate native-library installation. PyPI also publishes Python 3.12
macOS and Linux wheels; those platforms were not executed here. To require wheels:

```sh
.venv/bin/python -m pip install --only-binary=TA-Lib,numpy -e .
```

The chosen Python/OS/architecture must have matching wheels. Otherwise an explicit
source build needs a compiler and CMake; upstream 0.8.3 downloads and verifies its
pinned C source during that build unless configured to use an existing C library.
For future cloud packaging, prefer matching Linux wheels and rerun fixtures on
that runtime. No cloud runtime or Wheelwright environment is changed here. NumPy's
resolved version is recorded above, not separately pinned by this project.

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
for code-level completion. Stochastic fixtures and pure crossings are implemented
below. Future acceptance includes independent real-data validation, RSI, durable identities,
deduplication, missed-session recovery, all-symbol data validation, then scheduling.

## Stochastic(14,3,3) — TA-Lib migration complete

The Principal selected TA-Lib for production Stochastic and future RSI mathematics.
Market Sentinel owns input/session validation, crossing semantics and availability;
there is no indicator registry or parallel custom smoothing implementation.

Public API in `market_sentinel.stochastic` is retained:

```python
from datetime import date, timedelta
from market_sentinel.stochastic import DailyOHLC, crossed_below_20, stochastic_14_3_3

# Synthetic caller-supplied dates, not actual exchange-calendar observations.
bars = [DailyOHLC(date(2026, 1, 1) + timedelta(days=i), 60, 110, 10, 60) for i in range(18)]
points = stochastic_14_3_3(bars)
assert (points[-1].raw_k, points[-1].k, points[-1].d) == (50, 50, 50)
assert crossed_below_20(20, 19.999999999) is True
```

Immutable `DailyOHLC(session, open, high, low, close)` inputs produce an immutable
point per supplied session: `session`, `raw_k`, `k`, `d`, `crossed_below_20`,
`zero_range`, and per-session `warnings`. Empty input returns `()`. Inputs are float64 arrays for this exact call:

```python
slow_k, slow_d = talib.STOCH(
    high, low, close,
    fastk_period=14, slowk_period=3, slowk_matype=0,
    slowd_period=3, slowd_matype=0,
)
```

Both moving averages are simple (type 0). **K/D come from TA-Lib.** `raw_k` is a
small, separately calculated **informational** value using the original 14-session
high/low formula, not a TA-Lib output and never a trigger. No custom K/D smoothing
remains. No prices, intermediate results or outputs are deliberately rounded.

### Verified numerical conventions and migration differences

The pre-migration implementation and fixtures are preserved in commit
`d086ff27863a78d90d59509a49fa187737c6f902`. Differences below are deliberate and
independently tested, not silently rewritten reference values.

| Concern | Prior custom implementation | TA-Lib migration |
|---|---|---|
| Raw K | First at observation 14 | Retained as informational at 14 |
| K/D warm-up | K at 16; D at 18 | STOCH exposes **both at 18** (lookback 17) |
| Earliest crossing | Observation 17 | **Observation 19**: first available K has no previous available K |
| Exact flat range | Raw/K/D unavailable in affected windows | Library returns numeric zero; Market Sentinel masks affected outputs as unavailable |
| SMA precision | `math.fsum` on each window | TA-Lib's rolling floating-point sums; tiny residuals possible |
| Machine-near-flat range | Exact-formula raw K | TA-Lib's relative zero tolerance may produce K/D=0 even for a nonzero range |
| Extreme finite magnitude | Safe custom formula could handle it | Reject OHLC when `high + low` is nonfinite; TA-Lib's magnitude guard would otherwise misleadingly return zero |

**Exact zero-range availability:** raw K is `None` with `zero_range=True` when the
14-session highest high equals the lowest low. K is masked if any of its three
contributing ranges is unavailable from warm-up or exact flatness; D checks five
contributing ranges. Overflow of informational raw K alone does not mask finite
TA-Lib K/D. This small validity mask retains the existing no-undefined-signal
policy. It performs no substitute indicator calculation and never skips a gap.
TA-Lib still computes K/D; after those affected windows pass, its outputs resume.

**Near-flat convention:** TA-Lib C 0.8.3 uses a scale-aware zero test against
`abs(highest) + abs(lowest)`. For low=100 and high=close=100+1e-12, informational
raw K is 100, but library K/D are 0. `zero_range` means **exact** zero range, so is
false in that fixture. This library numerical convention is adopted under the
TA-Lib selection; near-flat transitions can consequently differ from the prior
custom calculation. It is distinct from missing data and from the exact-flat mask.

**NaN/invalid data:** missing/nonfinite inputs fail before TA-Lib is called. Direct
library probing shows a NaN close can contaminate the remaining SMA series rather
than recover after its nominal window; H/L NaNs can contaminate later. Market
Sentinel never passes these inputs or fills them. Nonfinite library outputs map to
`None`; adjacent unavailable K values cannot establish a crossing.

**Floating-point behavior and accepted warned data:** outputs are never clamped
or rounded. Finite K/D may be outside [0,100] when a reported close is outside its
rolling range; the Principal's screening policy accepts those numerical outputs.
`crossed_below_20` therefore accepts finite values outside [0,100], retaining the
exact comparison `previous >= 20 and current < 20`. Nonfinite inputs to the helper
remain errors; unavailable library outputs become `None` and cannot establish a
crossing. This supersedes the former bounds guard, without changing the threshold,
SMA parameters, direction or adjacent-session semantics. Raw K and D never trigger.
A recovery to exactly 20 or above permits a subsequent crossing. No durable event
identity, re-arming store, notification or deduplication is implemented.

### Input and validation contract

Supply one security's chronological completed sessions on a consistent OHLC
adjustment basis. Session identity must be `datetime.date`, not string/datetime;
dates must strictly increase without duplicates. All OHLC fields must be finite
Python int/float values (not booleans/strings), with
`open > 0`, `close > 0`, `0 < low <= high`, and safe magnitude as described above.
Open/close outside [low,high] remain unchanged and produce `RangeWarning` records
(`session`, `code`, `value`, `low`, `high`) on each corresponding point. Structurally invalid
records/values/order raise `ValueError`; a missing dataclass constructor argument
raises `TypeError`. The entire input is validated before calculation.

The caller establishes consecutive completed trading-session coverage. This pure
layer cannot distinguish holidays from omitted sessions or infer market completion.
It does not sort, interpolate, fill, adjust prices, fetch data or retain state.
Revised observations must be supplied explicitly for recomputation.

### TA-Lib migration evidence

At the TA-Lib migration on November 2, 2026: **60 offline tests passed**, including all 20
unchanged Pushover tests, on Python 3.14.10. Editable and clean non-editable wheel
installation were exercised; package dependency checks and safe CLI behavior passed.

Hand-derived fixtures remain authoritative checks on standard arithmetic: fixed
range [10,110] and closes `10+x` give raw K=x. The unchanged reference sequence
`30,60,90,30,0,0,0,60,0,0,0` has mathematical K
`None,None,60,60,40,10,0,20,20,20,0` and first D `160/3`, then `110/3`.
TA-Lib withholds the two early K=60 values to align outputs; the exposed results
match within 1e-12. Existing flat-window and rolling-extreme fixtures are retained.
Tests explicitly classify changed availability, library tolerance, NaN propagation,
parameterization, bounds noise, unsafe magnitudes and full-precision crossings.

**TradingView comparison is no longer a mandatory acceptance gate or dependency.**
Independent synthetic references plus later, separately authorized real-data
validation replace it. The subsequent Tradier acceptance evidence is recorded
below. This earlier library migration itself acquired no prices or credentials.

Upstream sources checked November 2, 2026:
[Python package metadata/wheels](https://pypi.org/project/TA-Lib/0.8.3/),
[installation documentation](https://github.com/TA-Lib/ta-lib-python),
[STOCH C implementation](https://github.com/TA-Lib/ta-lib/blob/v0.8.3/src/ta_func/ta_STOCH.c),
[scaled-zero guard](https://github.com/TA-Lib/ta-lib/blob/v0.8.3/src/ta_func/ta_utility.h).

## Tradier — selected provider, 19-symbol informational reporting

The explicitly invoked command uses one `GET /v1/markets/history` per configured
symbol. It requests daily OHLCV over explicit dates and calculates Stochastic
using the same normalized bars a future RSI slice can reuse. There are no account,
order, options, notification, storage or scheduler operations. No new dependency.

### Warning versus failure policy

The Principal accepts mixed dividend-related historical close conventions for
screening. Tradier's documented basis is split-adjusted/dividend-unadjusted, but
observed pre-dividend closes can differ from that stated convention. **Use the
prices as supplied.** Do not correct dividends, alter high/low, clamp closes,
substitute previous prices, discard rows or reconcile providers automatically.

- **Warnings:** `close_below_low`, `close_above_high`, `open_outside_range`.
  Every occurrence records session, supplied value and low/high. Warned prices
  still enter TA-Lib and may establish a crossing. Reports are screening evidence,
  not independently verified market truth. Warnings on excluded rows remain
  visible and are labeled excluded from calculation.
- **Failures:** missing/malformed/nonfinite/nonpositive required prices, high < low,
  unsafe TA-Lib magnitude, malformed dates, duplicates or out-of-order sessions,
  invalid supplied volume, empty history and acquisition errors. Structurally
  invalid OHLC is identified as a failure, not a fourth nonfatal range warning.
- **Unavailable indicators:** warm-up, exact flat-range masks or nonfinite library
  outputs remain unavailable. Do not fabricate values or bridge missing K values.
  Nonfinite informational raw K also becomes unavailable if arithmetic overflows.

Chronology must be strictly increasing. The old normalization sort is removed;
`History.reordered` is retained for compatibility and is always false on accepted
input. Optional/null volume stays `None` and is reported. Invalid rows reject the
symbol, including invalid rows after the cutoff; no row is silently discarded.

### Interfaces, report and completion status

- `tradier.load_token(environment)` retrieves credentials separately.
- `tradier.fetch_history(token, *, symbol, environment, start, end, completed_through)`
  performs one fixed-endpoint HTTPS GET. `normalize_history(payload, **same_metadata)`
  is the pure validation entry point and returns immutable `History`, including
  chronological `DailyOHLC`, aligned volumes, exclusions and `warnings`.
- `tradier_report.history_report(history)` returns latest close/K/D, adjacent-bar
  crossing availability, historical crossings, warning counts/details, staleness,
  warm-up count and unavailable post-warm-up sessions.
- `python -m market_sentinel.tradier_report ... --fetch` evaluates the fixed universe
  once. JSON is labeled **Market Sentinel — Informational Screening Results** and
  includes a manual-review notice, UTC evidence timestamp and batch summary.

A finite warned result is `calculated_with_warnings`; warnings alone do not make
it incomplete. Summary statuses are `complete`, `complete_with_warnings`, or
`incomplete`. Acquired, evaluated and usable-latest symbol counts distinguish
successful zero-crossing runs from failures. Missing latest K/D, unavailable
adjacent K comparison or cutoff staleness is degraded; unavailable crossing flags
are JSON null. Historical warning details remain visible even when latest data
is usable. Repeating a report may show the same crossing: no durable deduplication.

A symbol-specific acquisition, data or calculation failure remains in the report
and evaluation continues for other symbols. Authentication/entitlement or quota
failure stops further requests, marking unattempted symbols explicitly. Exit 0
means all 19 latest evaluations are usable, with warnings allowed; exit 1 means
setup failure or incomplete evaluation; exit 2 means command misuse/no fetch intent.

The caller certifies the completed-session cutoff. Later rows are excluded before
calculation, never assumed complete because the API returned them. The CLI remains
conservative: end/cutoff must predate today in America/New_York and the cutoff
cannot be a weekend. Date ranges are bounded to 366 calendar days. The library
can accept a separately certified same-day cutoff; it does not establish finality.

**Calendar continuity is not implemented in the command.** Its report says
unverified; omitted weekdays cannot be distinguished from exchange holidays.
`complete` describes batch processing, not independent exchange-calendar proof.
Coverage is checked separately for the bounded live acceptance evidence. Daily-bar
publication timing, early-close handling and revision reconciliation remain
future monitoring work; 09:31/16:01 ET are research observation times, not validated
production evaluation times. No timing study or recurring polling is installed.

### Secure setup and operation

Keep the existing production token outside Git. In macOS Keychain Access → login
→ File → New Password Item, use service **`market-sentinel.tradier`**, account
**`production-token`**, and the token as its password. Sandbox uses the separate
account **`sandbox-token`** and matching token. Do not paste secrets into chat,
arguments, source, issues or logs. No credentials were created or changed here.

Portable alternative: securely inject `TRADIER_TOKEN` at runtime. It overrides
Keychain, including rejecting empty values. Hidden interactive zsh handoff:

```sh
(
  set +x
  read -rs 'TRADIER_TOKEN?Tradier production token (hidden): '
  printf '\n'
  export TRADIER_TOKEN
  # Run the authorized command below within this subshell.
)
```

Personal Tradier tokens grant full account access even though this code only
requests history. They persist until regenerated. No market-data-only personal
scope or OAuth flow is introduced. Keychain retrieval is limited to 15 seconds;
macOS may require operator approval. Environment values may be visible to
privileged local processes. Never reuse Pushover service identifiers or keys.

```sh
.venv/bin/python -m unittest discover -s tests -v
# Safe: no --fetch; reads no credentials, sends no requests, exits 2.
.venv/bin/python -m market_sentinel.tradier_report --environment production \
  --start 2026-02-01 --end 2026-10-30 --completed-through 2026-10-30
```

Append `--fetch` only for an authorized live run. This targets about 189 completed
sessions per symbol. For later runs, explicitly select a known completed exchange
session and sufficient preceding history; the command does not guess holidays.
Keep raw responses and operating reports outside the public checkout.

HTTPS uses normal TLS verification, no redirects/ambient proxies, a 15-second
network timeout, a 1 MB response cap and no automatic retry. Errors suppress raw
provider bodies, headers and credentials. Both HTTP 400 `Quota Violation` and 429
are recognized. Production market-data quota is documented as 120/minute/token;
sandbox 60. This command makes at most 19 sequential requests; sandbox's delayed
data is not equivalent evidence of production freshness.

### Bounded acceptance evidence — November 2, 2026

**115 offline tests passed** on Python 3.14.10/macOS arm64, including all unchanged
Pushover tests. Earlier strict range-rejection, sorted-input and three-symbol
expectations were explicitly updated for this Principal-authorized policy; the
underlying test cases were retained. New tests cover the three observed CLX/MCD
rows, unchanged source values, warning classes, finite out-of-range K/D, nonfinite
outputs, fatal input, partial failures and successful quiet/warned batches.

Production verification made exactly **19 history requests**, all HTTP 200.
Every symbol returned **189 completed sessions, February 2–October 30, 2026**.
A separate bounded check against the published exchange calendar found no missing
or unexpected dates. All latest K/D values and adjacent comparisons were usable;
there were **zero October 30 downward crossings** and **13 close-below-low warnings
across nine symbols**. The known CLX April 21 and MCD March 2/August 31 rows now
calculate with warnings and unchanged values. No symbol failed. Raw responses,
full-precision results, historical crossings, timestamps and hashes remain outside
Git. This establishes the bounded manual screening path, not daily-bar finality,
independently verified prices or unattended operation. No live notification sent.

Official references:
[history](https://docs.tradier.com/market-data/get-historical-pricing),
[market-data conventions](https://docs.tradier.com/docs/market-data),
[authentication](https://docs.tradier.com/docs/authentication),
[rate limits](https://docs.tradier.com/overview/rate-limits).

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
- Stochastic delegates K/D to TA-Lib with the explicit policies above. RSI will
  also use TA-Lib in a separate slice. Independent numerical fixtures and later
  real-data/session validation are required; TradingView comparison is optional.

**Data:** Tradier is selected. The 19-symbol informational command is implemented
above. Source OHLC is preserved, and accepted range warnings remain visible.
Future monitoring must establish completed sessions, calendar coverage, freshness
and revision handling. Missing data is failure, never proof of no crossing.

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
