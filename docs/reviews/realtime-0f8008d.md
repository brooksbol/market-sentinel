# Independent engineering review — REJECT

Reviewed immutable candidate: `0f8008df0690caa11cc872b889ae28845c351c72`.
Base main: `a41c91ddfddcf8022251b2bdece1e27851bff30e`.
The reviewed working tree was clean. No candidate edits were made.

Independent verification: `PYTHONPATH=src /Users/bollich/kiro/market-sentinel/.venv/bin/python -m unittest discover -s tests -q` — 229 tests passed in 2.667s.
Additional offline falsifiers below used synthetic data, temporary SQLite ledgers and mocked credentials/provider/transport. No credentials, provider calls, notifications, account connections, trades, installation or activation occurred during review.

## Findings requiring correction

1. **P1 — HTTP can begin after the regular-session close or freshness expiry.** `src/market_sentinel/realtime.py:37-40,73-76`. The final `run_once` clock guard occurs before `send_alert`, but `send_alert` performs potentially slow credential loading before HTTP without another clock/session/freshness guard. Existing loaders allow 15 seconds per Keychain item. Offline reproduction set the guard time to 15:59:59 Eastern, advanced 20 seconds in mocked `load_credentials`, and observed `_send_message` invoked at **16:00:19**; the event became `api_accepted`. Prepare credentials before the final guard or move the guard into the adapter immediately before HTTP. Retain the distinction between an intentionally withheld send and a potentially accepted HTTP attempt where practical. Add an offline slow-credential boundary fixture.

2. **P2 — older pending close follow-ups become permanently unresolvable and can starve newer follow-ups.** `src/market_sentinel/intraday_provider.py:30-41,50-63`; `src/market_sentinel/intraday_state.py:118-119`. Calendar acquisition is based only on current day minus275 days, whereas a pending event's history begins at its own session minus270. On a later restart, valid older history precedes the available calendar and is always rejected. Offline reproduction used current November30 calendar beginning February1, event session September15, and a complete193-bar synthetic history beginning December19: `Completed history coverage unavailable`. Since `pending_completions` always selects the oldest19, enough unresolved old entries also prevent later events from ever being followed up. Recover calendar coverage for each pending cutoff (or reuse adequate retained source evidence) and ensure one unresolvable batch cannot monopolize all follow-up work. Add a restart fixture with delayed old completion and newer events.

3. **P2 — auth/quota stop signals are ignored during completed-result follow-up.** `src/market_sentinel/realtime.py:83-92`. The main acquisition sweep handles `TradierError.stop_batch`, but follow-up swallows every exception and continues. Offline reproduction created19 pending symbol/session events and made the first `provider.completed` raise `TradierError(stop_batch=True)`; **all19** follow-up calls still occurred. Main-sweep auth/quota failure also does not stop the follow-up phase. Propagate a per-sweep stop condition across all provider acquisition phases; preserve deferred follow-ups rather than continuing requests after an entitlement/quota rejection.

4. **P2 — the acquisition deadline is not checked before each request.** `src/market_sentinel/intraday_provider.py:88-104`. The loop checks before the symbol's historical request but not again before its timesales request. A slow history call can use the remaining budget and still be followed by a newly started minute request. Offline reproduction advanced monotonic time to91 seconds in the first history fixture and observed a timesales request begin at91 seconds. This contradicts the documented guarantee that no new request starts after90 seconds. Check the common deadline before every request, including completed-result and calendar acquisition steps.

## Provider coverage and acceptance boundary

The implemented strict-continuity policy safely refuses incomplete minute series. It does not invent zero-trade intervals, interpolate prices or send alerts from missing evidence. That is a sound fail-closed engineering behavior and is not itself a request to weaken validation.

However, the implementer's retained feasibility summary says six of19 symbols had seven omitted minute intervals in a real production sweep. Because aggregation re-reads the entire session from the opening, any persistent omitted early minute makes the symbol unavailable for the rest of that session. Thus current evidence supports a **partial-coverage candidate**, not fulfillment of continuous usable all19-symbol monitoring. The acquisition contract still needs provider-backed sparse-interval semantics, demonstrated complete data, or a verified alternative candle path. Do not claim full mission success, production readiness or activation fitness from the mock all19 test. An operator decision to accept partial coverage would change the requested acceptance scope and must be explicit; implementation/test success does not ratify it.

## Positive evidence and non-blocking observations

- Existing completed Stochastic implementation is unchanged; provisional evaluation appends a distinct current-session bar and keeps completed K/D separate.
- Full-precision transitions, conservative once-per-session suppression, separate intraday identities, persistent intent-before-HTTP and no automatic replay are covered by passing tests and code inspection.
- Source OHLC and provisional events are retained; separate completion records avoid rewriting detection-time evidence.
- Daily scheduler change extracts the existing calendar validator without semantic alteration; legacy tests pass.
- Browser history default is preserved; realtime paths remain read-only and local. No frontend framework or brokerage account interface is added.
- Cloud design avoids a macOS dependency in the monitor core; operational storage, managed secrets and deployment remain unverified and unimplemented.
- A focused symbol page would benefit from a direct return-to-all19 realtime link, rather than only the report-history link. This is a small usability improvement, not a correctness rejection.

Disposition: **REJECT this candidate for engineering acceptance** until findings1–4 are corrected and independently rechecked. The provider coverage limitation remains a separate unresolved feasibility/acceptance boundary even after those defects are fixed. No installation or activation is approved by this review.
