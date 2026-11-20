# Market Sentinel — lightweight experiment method

**Status:** Working method, not authority to trade, change the live monitor, or expand scope.  
**Established:** 2026-11-05.  
**Purpose:** Keep trials reproducible and distinguish a plausible idea from demonstrated results. This is a two-document convention, not an experiment platform or governance process.

## One experiment, one dated record

Keep each actual trial in a dated Markdown file under `docs/experiments/`. The record should fit the question, not a prescribed form. Update the same file as outcomes mature; link source commits and contemporaneous evidence when available. Do not store credentials, account identifiers, private screenshots, raw runtime files or personal financial records in this public repository.

Use this compact sequence:

1. **Question / hypothesis:** What outcome is predicted, and what observation would weaken or refute it?
2. **Scope / regime:** Universe, time horizon, capital basis, signal semantics, trade lifecycle and what is explicitly excluded.
3. **Protocol:** Selection and execution rules established **before** evaluating outcomes. Mark changes as amendments with dates, never silently rewrite the original hypothesis.
4. **Observation:** When and where a fact was observed; completed-session data versus intraday provisional data; simulated versus actual execution; quote/indicator provenance.
5. **Accounting:** Track available cash, committed collateral, shares, open option liabilities, premium, fees, realized/unrealized P/L and net liquidation value separately. Gross premium is not profit; assignment capacity is not cash spent.
6. **Evaluation:** Count eligible signals, entries, fills, missed/ambiguous cases, assignments, calls, exits, roll decisions and adverse outcomes. Evaluate capital erosion and cash-flow sustainability along with income; don't assume a successful fill establishes a viable strategy.
7. **Disposition:** Supported / contradicted / inconclusive, outstanding evidence, and a separately authorized next increment.

## Evidence rules

- Label evidence as **observed completed-session**, **observed intraday**, **simulated fill**, **modeled/illustrative**, or **unverified**. Screenshots and remembered prices are not substitutes for timestamped machine-readable records.
- A daily Market Sentinel report is an **attention mechanism**, not a trade trigger, recommendation, or proof of intraday conditions. Do not backfill an intraday rationale from a later daily bar.
- Record precise signal definition (e.g., K/D direction, level, completed versus provisional bar, comparison session), including changes or ambiguity. A threshold approach is not a confirmed crossing.
- Record option symbol, expiry, put/call, strike, quantity, bid/ask and observation times where available; attempted limit, revisions, actual simulator fill and fees separately. Midpoint and paperMoney fills are **not verified real-money executable prices**.
- Record the intended lifecycle: cash-secured approximately ATM short put with assignment acceptable, then approximately 16-delta covered calls with long-term retention bias. A put fill alone does not test the whole lifecycle.
- Preserve **evidence gaps explicitly**; never invent missing expirations, fills, premiums, deltas, dates, or outcomes.
- Keep Wheelwright/options-prototype experiments and Market Sentinel observations separate unless a later explicit composition contract and study scope authorize combining them. Market Sentinel owns its independently commissioned analytics and attention; financial eligibility and execution require their own evidence.
- Be alert to survivorship, hindsight, slippage, option-chain liquidity, fill selection, regime shifts, taxes/fees where material and capital constraints. No single attractive trade is statistical proof.

## Practical comparison questions

- Did the predeclared indicator rule generate an entry **before** the price/option outcome was known?
- Could the operator transact near the assumed quote, after spreads, fees and repricing? How frequently did simulator orders remain unfilled?
- How much collateral was tied up, for how long, and what was the opportunity cost?
- What fraction of trades progressed to assignment, covered calls, rolls or exits? What were the total-return and downside outcomes—not simply collected premium?
- Does the approach replenish the planned cash ladder without forcing trades or increasing risk as capital erodes? Distinguish cash-flow timing from economic earnings.

No mandatory tooling, data schema, dashboard, scheduled study, or new infrastructure is authorized by this document.
