# Independent engineering rereview — ACCEPT bounded candidate

Reviewed immutable candidate: `f02ff98661e5a69f0abd0b9553d2eb3c33e6a0bc`.
Prior rejected candidate: `0f8008df0690caa11cc872b889ae28845c351c72`.
Base main remains `a41c91ddfddcf8022251b2bdece1e27851bff30e`.
The candidate worktree was clean and was not edited during review.

## Disposition

**ACCEPT for bounded engineering publication.** The four reproducible defects in the prior review are corrected. No new blocking engineering finding was established in the affected changes.

This disposition does **not** accept complete all19-symbol operational coverage, production readiness, Principal operator acceptance, installation or activation. The provider-data completeness issue remains an external feasibility/acceptance blocker, described separately below.

## Independent verification

Command: `PYTHONPATH=src /Users/bollich/kiro/market-sentinel/.venv/bin/python -m unittest discover -s tests -q`.
Result: **234 offline tests passed in 2.644 seconds**.

Additional independent synthetic falsifiers re-exercised the original failures:

1. A mock credential lookup advanced15:59:59 Eastern by20 seconds. The new transport callback ran after credential/request preparation and prevented any HTTP call. Outcome remained conservatively `acceptance_unknown`, with no automatic retry. The old after-close send reproduction is closed.
2. A November30 invocation reconciled a September15 event with a complete193-bar history beginning December19, after recovering missing December/January calendars. Completed K25 was accepted; the old rolling-calendar rejection is closed. Inspection and the added rotation fixture verify that least-recently-attempted pending work allows newer follow-ups to advance despite older unavailable work.
3. Nineteen pending symbol follow-ups were created. The first synthetic auth/quota `stop_batch` error yielded exactly **one** completed acquisition call. The main-sweep failure path also marks acquisition stopped before follow-ups. The old continuing-batch reproduction is closed.
4. Mock history acquisition advanced monotonic time to91 seconds. No timesales request was started. Guards also cover calendar/history requests after credential preparation and completed-result acquisition. The old over-budget request-start reproduction is closed.

## Latest user sorting amendment

Daily browser detail and realtime rows default to full-precision K ascending and expose D ascending links. Missing/nonfinite values sort last with symbol tie-breaking; displayed rounding is not the sort input. An independent browser-HTML fixture used CLX/CVX at equal full-precision K19.9991, XOM K19.9999, and different D values: K order was CLX/CVX/XOM; D order was CLX/XOM/CVX. This fixture did not reuse the implementation's order function for expected results. The suite also verifies daily-browser ordering, realtime ordering and missing values.

The new user instruction legitimately supersedes prior row priority by recent crossings. Recent intraday events remain in their separate section. The focused view now links directly back to all19 realtime symbols. Daily Pushover sorting remains unchanged.

## Regression, provenance and portability assessment

The completed-session Stochastic implementation remains unchanged. The shared Pushover transport's optional pre-request callback is absent for existing daily-report/test callers, preserving their request semantics; all existing transport/scheduler/calculation/history tests pass. No new credential dependency is introduced for viewing or preview generation.

The corrected source evidence includes calendar sessions supporting historical continuity, plus acquisition timestamp and provider identity. Event evidence and separately retained completed-close results remain distinct and immutable. Intraday event/notification identities remain separate from scheduled daily reports.

The core continues to avoid macOS startup dependencies; SQLite still requires a suitably durable single-writer/concurrency deployment model in any later cloud environment. Neither cloud hosting nor remote authenticated dashboard operation is implemented or verified by this review.

## External provider coverage blocker remains

The retained feasibility summary records seven missing minute intervals across six of19 symbols in the real production probe. Strict session-long minute continuity correctly suppresses those symbols, rather than inventing empty-minute semantics or filling candles. A persistent early missing interval can therefore prevent usable observations for that symbol throughout that session.

The candidate is a tested, fail-closed **partial-coverage-capable implementation**. It is not evidence that the commissioned all19-symbol attention objective is fully achieved. Completion of that objective requires provider-backed sparse-interval semantics, demonstrated complete series or a verified alternative complete-candle acquisition path. Accepting partial coverage instead would be a Principal Product decision, not a consequence of this engineering ACCEPT. No actual provider limitation was silently repaired or waived in rereview.

Operational acceptance also remains separate for cadence/freshness policy, sustained running-time behavior, state growth/retention, signed data/hosting entitlements, actual notification delivery/phone receipt and deployment. No production-readiness claim follows from offline tests.

## Review boundaries

No candidate modifications, real credentials, external provider calls, actual notifications, brokerage connections, trades, installation, scheduler changes or cloud activation occurred during this rereview. All additional data, credentials, provider functions and transport functions were synthetic or mocked; SQLite evidence used temporary directories outside the repository.
