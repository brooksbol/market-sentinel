# Market Sentinel

An independent utility for monitoring technical-indicator crossings on 19 fixed
equities and notifying one operator. Notifications support manual review; they
never authorize or execute a trade.

## Current scope

Repository foundation, a bounded Pushover transport proof, and pure standard
Stochastic(14,3,3) calculation with adjacent-session crossing detection. The market
monitor is **not implemented**: no market-data connection, RSI, database, durable
events, daily receipt or installed scheduler exists. Stochastic results are not
connected to Pushover. This project has no Wheelwright runtime, deployment,
credential or Product dependency.

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
`zero_range`. Empty input returns `()`. Inputs are float64 arrays for this exact call:

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
raw inputs are unavailable; D is masked if any of its five contributing raw inputs
are unavailable. This small validity mask retains the existing no-undefined-signal
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

**Floating-point boundaries:** a recovery fixture yields D about -1.9e-14 rather
than mathematical zero. Values are not clamped. The crossing helper permits only
1e-10 of numerical spill beyond [0,100], while rejecting larger out-of-range
values. **There is no tolerance at threshold 20:** compare the actual unrounded
`previous >= 20 and current < 20`. Last-bit differences from custom summation can
change a classification extremely close to 20; TA-Lib is now calculation authority.
Raw K and D never independently trigger, and consecutive below-20 values do not
repeat. Recovery to exactly 20 or above allows a later crossing. No durable event
identity, re-arming store, notification or deduplication is implemented.

### Input and validation contract

Supply one security's chronological completed sessions on a consistent OHLC
adjustment basis. Session identity must be `datetime.date`, not string/datetime;
dates must strictly increase without duplicates. All OHLC fields must be finite
Python int/float values (not booleans/strings), with
`0 < low <= open/close <= high`, and safe magnitude as described above. Invalid
records/values/order raise `ValueError`; a missing dataclass constructor argument
raises `TypeError`. The entire input is validated before calculation.

The caller establishes consecutive completed trading-session coverage. This pure
layer cannot distinguish holidays from omitted sessions or infer market completion.
It does not sort, interpolate, fill, adjust prices, fetch data or retain state.
Revised observations must be supplied explicitly for recomputation.

### Verification and remaining evidence

Verification on November 2, 2026: **60 offline tests passed**, including all 20
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
validation replace it. Real-data coverage, source adjustments and session timing
remain unverified; no prices or credentials were acquired in this migration.

Upstream sources checked November 2, 2026:
[Python package metadata/wheels](https://pypi.org/project/TA-Lib/0.8.3/),
[installation documentation](https://github.com/TA-Lib/ta-lib-python),
[STOCH C implementation](https://github.com/TA-Lib/ta-lib/blob/v0.8.3/src/ta_func/ta_STOCH.c),
[scaled-zero guard](https://github.com/TA-Lib/ta-lib/blob/v0.8.3/src/ta_func/ta_utility.h).

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

**Data:** Tradier is the first candidate for a separately authorized market-data
feasibility investigation, not a final provider selection or integration. Establish
historical OHLC availability, entitlement, adjustments, coverage and freshness. Acquire
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
