# Realtime engineering delivery — November 5, 2026

**Status: independently accepted bounded candidate, not installed or activated.
Full all-19 usable market-data coverage remains blocked.**

1. **Remote main:** initial bootstrap `ead051f9446fa9977abd99d36d16aff3037565de`;
   integrated/reverified main `a41c91ddfddcf8022251b2bdece1e27851bff30e`.
2. **Discovery:** existing checkout `/Users/bollich/kiro/market-sentinel`;
   installed history precedent `/Users/bollich/kiro/market-sentinel-history`,
   branch tip `498bdd60a3f222a00683a538c5062eed88a96816`. Isolated implementation
   `/Users/bollich/kiro/market-sentinel-realtime`, branch
   `codex/realtime-sentinel-20261105`. Unrelated work preserved.
3. **Authority and sources:** Principal realtime commission and later K/D sorting
   direction, repository `AGENTS.md`, README/ROADMAP, existing Stochastic,
   Tradier, Pushover, calendar and history-viewer primitives. Detailed contract
   and official source links: [realtime.md](realtime.md).
4. **Provider:** 23 bounded production market-data GETs, all19 fresh quote/minute
   access verified on this occasion; no account endpoints. Seven missing minute
   intervals across CLX, ADM, TGT, SWK, SHW and TROW prevent full usable coverage
   under strict continuity. No empty-minute semantics inferred or prices filled.
   Sandbox's documented15-minute delay is unsuitable. Signed rights, sustained
   latency and exact future hosting permissions remain separately unverified.
5. **Cadence/latency:** provisional180-second pause after each sweep; all19 live
   minute probe measured12.159 seconds. Completed-minute inputs add up to a minute
   of formation delay plus publication latency. Roughly3–5-minute detection under
   observed conditions is an estimate, not a tick service or end-to-end SLA.
6. **Calculation:** existing TA-Lib(14,3,3), unchanged SMA types/precision/masks;
   append exactly one current-session candle aggregated from complete regular
   minute OHLC. Completed baseline and source warnings retained separately.
7. **Crossings:** previous full-precision K>=20 and current K<20; initial first
   sighting below prior completed K explicitly qualified; recovery retained;
   known gaps qualified and downward alerts suppressed. First downward event per
   symbol/session can reserve one notification; repeated/recovered crossings do
   not re-arm push. Preview/gap events consume this conservative budget too.
8. **Persistence:** independent private SQLite; source bars/calendar, observations,
   transitions, suppression, committed notification intent/outcome, sweep failures
   and separate first completed-close follow-up retained. No event rewriting;
   restart never automatically replays uncertain sends. Preserve/back up ledger.
9. **CLI/dashboard:** `sentinel` keeps report history; `sentinel --realtime` and
   `sentinel --realtime XOM` read the monitor ledger and refresh every15 seconds.
   Both daily browser details and realtime rows default to K ascending; D ascending
   links, full precision sorting, missing last, symbol tie-break. Focus exposes
   baseline/current OHLC/provenance. Viewing never starts acquisition or sending.
10. **Push:** existing Pushover transport/limits, symbol/previous-current K/price,
    observation and detection times, explicit provisional/unconfirmed status.
    Default preview sends nothing. Authorized future `--send` reserves intent
    before HTTP; deadline/freshness guard runs after credential preparation.
    Acceptance is not phone receipt; failures/interruptions are not retried.
11. **Cloud:** portable core/provider/state/monitor separation. Managed secrets,
    durable storage/concurrency, scheduler, authenticated remote presentation,
    operations, retention and provider terms must be supplied/verified later.
    No cloud migration commissioned or implemented.
12. **Regressions:** existing204 tests plus30 intraday/sorting/boundary tests pass.
    `stochastic.py`, `daily_report.py`, universe and completed report acquisition/
    evaluation remain byte-identical to baseline. Calendar validator moved without
    semantic changes; optional transport guard leaves existing callers unchanged.
13. **Independent review:** [0f8008d rejected](reviews/realtime-0f8008d.md) for four
    reproducible defects, then [f02ff98 accepted for bounded publication](reviews/realtime-f02ff98.md).
    All four corrections independently reproduced. Full provider coverage remains
    an external blocker, not waived by review or tests.
14. **Files changed in realtime increment:** `intraday.py`, `intraday_provider.py`,
    `intraday_state.py`, `realtime.py`, `realtime_view.py`, `sessions.py`;
    bounded edits to `report_history.py`, `scheduled_report.py`, `tradier.py`,
    `pushover.py`; `tests/test_intraday.py`; README/ROADMAP and these focused docs/
    review receipts. The branch additionally carries prior published history-viewer
    files/packaging/tests from9e4e8e9 and498bdd6, absent on main; it reuses that
    installed working precedent rather than rebuilding it.
15. **Verification:** implementer234 offline tests passed; independent reviewer
    reproduced234 passes in2.644 seconds plus separate falsifiers and independent
    K/D ordering expectations. No real credentials/external provider required by
    routine tests. Synthetic loopback all19/focused view visually verified in Safari;
    sorting validated offline, temporary server stopped. Help commands verified.
16. **Reviewed code identity:** `f02ff98661e5a69f0abd0b9553d2eb3c33e6a0bc`.
    Subsequent publication receipt changes are documentation only. Final publication
    tip and remote verification are reported by the implementing actor; branch/PR
    publication does not imply main merge, installation or activation.
17. **Unresolved:** provider-backed sparse-interval contract or another verified
    complete regular-session candle path. This is the smallest data-contract work
    needed to achieve the requested all19 outcome. Accepting partial coverage would
    require an explicit Principal scope decision. Cadence, first-sighting/dedup,
    actual delivery, running-time behavior, state growth/retention, signed data
    rights and deployment also require operational acceptance before activation.
18. **Unchanged operational boundaries:** no real notifications, trading actions,
    brokerage-account requests, credential changes, scheduled jobs or cloud
    resources were changed. Existing credentials were read only for the explicitly
    commissioned bounded market-data feasibility probe, never routine tests.
19. **Installation/activation:** neither performed. Existing installed daily reports
    and history command continue from their prior source/environment. No production
    readiness or full mission-success claim is made.
