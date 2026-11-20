# 2026-11-05 — Aristocrats paperMoney acquisition experiment

**Status:** Active exploratory paper-trading record; no live-money performance established.  
**System:** thinkorswim paperMoney, monitored against Market Sentinel's fixed 19-symbol Aristocrats universe.  
**Companion method:** [experiment-method.md](../experiment-method.md).  
**Related but distinct:** Codex's ongoing experimental gap analysis concerns Wheelwright's `options-prototype` repository; its findings are **pending**, not incorporated here. This is not the live $5,000 TT1 bull-put-spread experiment.

## Objective and operating thesis

Test the **acquisition leg** of the Aristocrats lifecycle in simulation before deploying significant capital:

1. Market Sentinel's completed-session TA-Lib Stochastic (14,3,3) report narrows attention to interesting names; it is **not a decision indication**.
2. The operator checks intraday thinkorswim indicator and options-chain conditions. A Stochastic crossover is the intended execution cue; the contemporaneous discussion also referenced an oversold threshold, so the exact combination of direction, threshold and bar-completion conditions needs to be pinned down prospectively rather than inferred after fills.
3. Enter approximately at-the-money **short puts** with willingness and capital capacity to accept assignment; then, once shares are held, consider approximately **16-delta covered calls** with a retention bias.
4. Judge lifecycle economics, assignment exposure, fill feasibility, collateral utilization, drawdowns and potential contribution to the planned Treasury-ladder replenishment—not just initial credit received.

The broader, **provisional** portfolio benchmark earmarks about **$390,000** for the 19-name Aristocrats share/option sleeve, plus a separate $120,000 12-rung T-bill liquidity ladder and other longer-duration holdings. T-bill maturities return principal, **not earnings**, and a paperMoney result cannot validate replenishment.

## System context at start of study

- Market Sentinel automatically sends opening/closing completed-session reports through Pushover. A successfully received phone push was previously confirmed; the push is an **attention getter** only.
- Opening report on November 5 referenced the **completed November 4 session**: 19/19 evaluated with **zero completed-session crossings**. Examples cited in discussion: CAT K≈6.04 / D≈5.46; ADM K≈7.72 / D≈7.73; XOM K≈25.18 / D≈50.63; CVX K≈34.22 / D≈58.34; NUE K≈61.67 / D≈75.68. Values are historical daily observations, **not contemporaneous intraday readings or trading advice**.
- The operator explicitly corrected a daily-versus-intraday mismatch: **intraday thinkorswim observations**, not the daily Pushover summary, motivated paper orders. Some conversations described a crossover as the cue; whether it must be an oversold crossover and how an unfinished bar is treated remain experimental definitions.
- Thinkorswim paperMoney showed the 19-name watchlist with approximately **$390,919** account value in one observed screenshot. Another observed net liquidation value was **$389,897.94** at a different point. Do not treat these as reconciled snapshots or use their difference as measured P/L; capture exact timestamps, cash/equity components and open option liabilities first.

## November 5 chronological observations (relative sequence, not verified timestamps)

| Event | Observed / reported | Evidence qualification |
| --- | --- | --- |
| Screening | CAT and ADM deeply oversold on prior completed session; XOM and CVX were monitored as intraday conditions changed. | Daily and intraday measurements must not be conflated. |
| Entry mechanics | XOM order initially did not fill; operator retried/replaced. | Simulated order management, not proof of executable real fill. |
| CAT fill | CAT put filled without a subsequent manual price change after waiting. | Simulator fill latency was noteworthy; order history needed for exact bid/ask and fill time. |
| ADM | Put reported filled while the operator noted ADM remained below a threshold. | Exact intraday K/D, crossing direction, expiry, order limit and fill price not captured in this record. |
| CVX | Operator identified an intraday crossover, submitted a put order, waited and eventually repriced to the bid; fill reported. | Explicit example of intraday cue and simulated execution friction. |
| NUE | Approaching a monitored threshold / crossover condition, but **not yet meeting the operator's oversold threshold** when discussed; no paper position was confirmed. | Watch-only, not a trade or completed signal. |
| Closing observation | PaperMoney displayed four positions (ADM, CAT, CVX, XOM) and no working orders in a later screenshot. | Snapshot description; full audited activity export not yet attached. |

The operator observed that paperMoney fill behavior felt surprisingly similar to actual Fidelity fills, while explicitly noting the simulator's mechanism was unknown. This is **anecdotal**; it does not establish real-world fill equivalence.

## Simulated put positions observed

The following are **paperMoney positions**, not actual broker holdings. One contract / 100-share equivalent is assumed only where the described assignment exposure implies it; obtain the order-history export before treating quantities as audited.

| Underlying | Short-put strike | Assignment notional (100 shares) | Notes |
| --- | ---: | ---: | --- |
| CAT | $560 | $56,000 | Put reported filled after a delay; expiration/premium not independently recorded here. |
| XOM | $170 | $17,000 | Put reported filled after order replacement; expiration/premium not independently recorded here. |
| ADM | $72.50 | $7,250 | Put reported filled; expiration/premium not independently recorded here. |
| CVX | $220 | $22,000 | **December 18, 2026** put reported filled at **$11.50** premium/share ($1,150 gross per contract); gross assignment notional $22,000; simple strike-minus-credit $208.50/share *before fees*, conditional on assignment and without other adjustments. |
| **Total** | | **$102,250** | ≈26.2% of $390,000 **gross assignment obligations**, not net debit, realized loss or required full economic capital. |

No assignment, stock purchase, covered-call sale, roll or final P/L was established today. The CVX credit was a simulator fill, not proof of an executable live bid. Do not call collected put credits realized profit while short option liabilities remain.

## What today's experiment does and does not demonstrate

**Observed:** Four ATM/near-ATM put entries could be placed in paperMoney under the operator's intraday Stochastic workflow; some fills required waiting/repricing. Screening attention and execution were deliberately separated. Collateral exposure became material before the assignment/covered-call phase.

**Not yet established:** Prospective unambiguous crossover definition; precise indicator timestamp/values at each decision; quote quality and achievable live fills; consistent expirations/deltas/premiums and fees; assignment probability; subsequent covered-call retention economics; net portfolio return; adverse-tail exposure; cash-ladder replenishment; out-of-sample/regime robustness.

A daily completed-session report showing **zero new crossings** does not contradict intraday observed crossings or a paper trade. It merely answers a different question on a different observation clock.

## Framework for continuing this exact trial

For each next signal/trade, record **before or at decision time**: date/time and zone, symbol, observed intraday K/D and source/bar status, prior K/D if crossing is asserted, oversold threshold and direction rule, option expiry/strike/quantity/delta, bid and ask with timestamp, intended limit, attempts/repricing and simulator fill. Then maintain collateral, cash, open option liability, commissions, dividends, share basis, eventual assignment, covered-call legs and full P/L as separate fields. Capture unfilled qualifying candidates, including NUE-type watches, to reduce selected-fill bias.

**Hypothesis test:** Over a meaningful prospective sample, does a predeclared crossover-based Aristocrat acquisition process obtain plausible executable entries and produce acceptable *full-lifecycle* risk-adjusted outcomes without compelling trades to satisfy monthly cash needs? Today's four simulated fills are an initial mechanics test, **not an affirmative result**.

## Other Market Sentinel work and boundaries noted

- The local report-history viewer and PATH command `sentinel` had been built and published earlier on `codex/local-report-history` (commit `498bdd60a3f222a00683a538c5062eed88a96816`, reported 204 tests). These features remain separate from this experiment and, at time of this record, are **not part of main**. The browser reads existing reports; it does not supply intraday trading signals.
- Draft cross-repository Wheelwright/Market Sentinel integration boundary remains on `draft/wheelwright-integration-boundary` (not ratified and not merged). If adopted, Wheelwright-governed capabilities are consumed only through its published interfaces; Market Sentinel can own independent technical monitoring and attention. No integration is commissioned here.
- Do not change the existing scheduled production report, Pushover notifications, credentials, market data acquisition, or delivery ledger as a consequence of this experiment.
- Codex is separately conducting an **experimental gap analysis in `options-prototype`**. No result should be assumed until reviewed.

## Record provenance and limitations

This account consolidates operator descriptions and assistant interpretations from the November 5 paper-trading discussion, plus previously reported repository/notification status. Numerical values and order details should be reconciled against timestamped thinkorswim exports/screenshots before being used as analytic results. The document deliberately does **not** invent missing order metadata or claim actual execution. No future experiment, trading activity or system development is authorized by this retrospective record.
