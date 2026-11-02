# Market Sentinel — delivery and cloud pilot roadmap

_Status: November 2, 2026. Planning document, not authorization to implement subsequent stages._

## Purpose and boundaries

Market Sentinel is a small, independent, deterministic daily technical-indicator monitor for a fixed universe of 19 equities. It is an attention mechanism for informational oversold screening and eventual accountable daily results. The Principal accepts imperfect Tradier history and occasional extra or missed signals; the operator independently reviews all opportunities. The operator makes all investment decisions. It is **not** a trading bot, brokerage integration, stock picker, Wheelwright extension, or general technical-analysis platform.

A secondary objective is to use Market Sentinel as a **low-risk cloud deployment pilot before considering Wheelwright migration**. Reuse operational lessons, not runtime dependencies, databases, credentials, services, or governance. Wheelwright remains independently operated and governed.

This concise roadmap is explicitly requested by the Principal; it does not create an ADR system, project journal, or standing authority to expand scope.

## Current baseline

- Repository foundation and standalone Pushover transport-test CLI implemented at `d5c49ec6f6a81b1218b16162cac73ee67323a427`.
- Production indicator mathematics now use TA-Lib Python/C 0.8.3 (Principal-selected); NumPy is a transitive dependency. Python 3.14 macOS arm64 wheel installation is verified.
- Operator reported a successful authorized live Mac → Keychain → Pushover → iPhone test and confirmed the received message by screenshot.
- The historical three-message RETEST was independently confirmed on the locked iPhone with audible sound. Unattended scheduled operation remains unverified.
- Pure Stochastic was implemented at `d086ff27863a78d90d59509a49fa187737c6f902`; the bounded TA-Lib migration is verified by independent numerical fixtures and library-convention tests. See README for explicit warm-up, zero-range and precision differences.
- **Tradier is selected by explicit Principal decision.** The fixed 19-symbol report preserves supplied prices, warns on close/open outside high-low, and continues usable calculations. Missing/nonfinite/nonpositive or structurally invalid input remains fatal per symbol. Mixed dividend-related close conventions are accepted for screening without correction.
- Full 19-symbol daily-universe formatting and explicit one-message Pushover delivery are implemented. It replaces the generic keep-alive and remains separate from future actionable new-crossing alerts. No RSI, event persistence, automatic daily delivery or scheduler is implemented.
- TradingView comparison is no longer mandatory. Independent numerical fixtures and later real-data/session validation supply acceptance evidence.

## Incremental milestones

The sequence below is a working plan, not a collection of pre-authorized development assignments. Each slice should be explicitly commissioned, independently tested, reviewed, and stopped at its boundary.

| Slice | Goal and acceptance evidence | Exclusions / dependency |
| --- | --- | --- |
| 0 — Transport proof | **Complete:** fixed test message accepted by Pushover and operator-confirmed on iPhone; offline tests. | Does not establish unattended execution or a functioning monitor. |
| 1 — TA-Lib Stochastic | **Complete:** STOCH(14,3,3), explicit SMA types, full-precision K crossings and independent fixtures. Raw K is informational at 14; TA-Lib exposes K/D at 18. Exact-zero-range outputs remain unavailable through a small validity mask. | No provider, live push, state or scheduler. Numerical convention differences are documented in README; TradingView is optional. |
| 2 — TA-Lib RSI | Future separately authorized slice: Wilder RSI(14) via TA-Lib, independent fixtures/crossings, initialization and edge-case evidence. | No custom RSI implementation, automatic trading or market-data retrieval. |
| 3 — Tradier acquisition and screening | **Implemented:** all 19 fixed symbols, one daily-history request each, TA-Lib Stochastic, structured range warnings, visible failures/unavailable values and aggregate completion status. Offline and bounded production acceptance evidence is recorded in README. | No corrections, reconciliation, support investigation, RSI, notifications or scheduling. Calendar automation, same-day publication timing and revision recovery remain future work. |
| 4 — Durable monitoring | SQLite or another explicitly selected durable store for source provenance, runs, per-session events, notification attempts and delivery outcomes; independent re-arming, replay/catch-up, and ordinary duplicate suppression. | Exactly-once event recording cannot guarantee exactly-once push receipt. Cloud persistence choice must be decided before committing to a local SQLite deployment model. |
| 5 — Daily universe report | **Operator-friendly formatter and explicit delivery implemented:** all 19 rows sorted by unrounded K/symbol; close, whole-number Stochastic score, Oversold/Neutral/Overbought state. Exact 20/80 are Neutral; D stays internal. Unavailable-K rows sort last; incomplete diagnostics visibly reduce successful evaluation count. Distinct crossing/oversold/overbought counts, sample/session warnings, monospace and 1,024-character preflight. Retained October 30 body is 735 characters/UTF-8 bytes. Previous K/D report and revised score/state report phone receipt confirmed; revised layout accepted by operator. | Durable per-session progress and automatic delivery remain planned. Incomplete reports explicitly show unavailable/failed rows and incomplete crossing counts. Reject malformed/stale/mixed-session/oversize input; never silently omit rows or substitute prices. Actionable crossing alerts remain separate. |
| 6 — Local unattended operation, if still useful | launchd approximately 18:37 America/New_York, exchange-calendar handling including holidays/early closes, startup/wake catch-up, and verified unattended secret access. | Mac can be asleep; catch-up delay is accepted. No GitHub Actions scheduler. |
| 7 — Cloud execution pilot | Run an isolated, manually triggered cloud deployment with managed secrets, fixed Pushover **test** only, clear logs, exit status and independently confirmed iPhone receipt. | Explicit operator approval for cloud account, any expense, credentials and real push; no live market signal required. |
| 8 — Cloud monitor pilot | Add a cloud schedule, durable cross-invocation state, catch-up, failure visibility and deployment/rollback procedure. Validate quiet days, signal days, partial failures, restarts and duplicate suppression against acceptance evidence. | Do not migrate Wheelwright as part of this stage. |

The cloud transport experiment (slice 7) could be brought forward after the existing proof without waiting for the full monitor, if the Principal explicitly chooses that order. Do not conflate transport portability with complete monitor readiness.

## Cloud portability principles

Keep the six responsibilities separable: scheduling, OHLC acquisition, pure indicator calculation, crossing detection, event persistence, and notification transport.

- **Secrets:** Local macOS Keychain is an adapter, not the application's credential architecture. In cloud, use least-privilege managed secrets or securely injected runtime environment values. The existing Pushover client already accepts a complete environment credential handoff. Do not commit secrets or expose them in logs/arguments.
- **Execution:** Prefer a small periodic serverless job/function over an always-on VM unless measured requirements justify otherwise. Candidate stacks for a later decision include Google Cloud Run Jobs + Scheduler + Secret Manager or AWS Lambda + EventBridge Scheduler + Secrets Manager. **No provider is selected.**
- **State:** Serverless filesystems may be ephemeral. A local SQLite file is not durable unless the storage and concurrency model explicitly make it so. Compare a suitable persistent volume with a managed durable store before building cloud state handling.
- **Delivery semantics:** Distinguish scheduler invocation, successful session evaluation, API acceptance, and phone receipt. Retries after ambiguous timeouts may produce duplicate pushes; preserve attempts and operator-visible status.
- **Operations:** Prove deployment from GitHub, identity and least privilege, log redaction, alerts on failed/missed runs, deterministic replay, backups or retention where needed, rollback, and reproducible recovery.
- **Cost:** Establish budget alerts and measure actual charges, including secrets, storage, logging, networking and scheduling; do not assume a permanent $0 operating cost.

## Cloud pilot acceptance gates

1. A deployment can be reproduced from a specific reviewed GitHub SHA with no laptop-local files or secrets.
2. The runtime identity can read only Market Sentinel's secrets and required resources.
3. A manually authorized cloud transport test obtains API acceptance and the operator confirms phone receipt.
4. Logs, errors and build artifacts contain no credentials or sensitive runtime state.
5. When a schedule is later introduced, missed/failed invocations become visible; recovery and chronological catch-up are demonstrated.
6. Monitoring state survives termination, redeployment and restart; retries do not create ordinary duplicate events.
7. Operating cost and rollback/recovery procedures are demonstrated at the intended scale.

## Lessons transferable to Wheelwright — without integration

The pilot should provide *documented evidence* about reproducible deployment, secret lifecycle, scheduling and alerts, durable state, failure/retry semantics, observability, rollback and real costs. Those practices can later inform Wheelwright's own architecture assessment. No migration commitment, shared deployment or Wheelwright code change is authorized by this roadmap.

## Decisions still open

- Whether and when to run the cloud transport experiment relative to the market-monitor slices.
- Cloud provider and service selection, region, account, budget, operational ownership and permissions.
- Durable state architecture for serverless execution versus local SQLite.
- Whether local launchd remains necessary after a successful cloud monitor pilot.
- Exact operational acceptance thresholds and alert escalation for missed receipts.

**Next proposed engineering slice:** separately authorize TA-Lib RSI with independent offline fixtures. **Next data work:** separately scoped completed-session/calendar and freshness/revision handling when commissioned; the provider decision is settled. **Next cloud decision:** a narrowly scoped, manually invoked, fixed-message cloud transport proof when ready. None is authorized merely by this roadmap.
