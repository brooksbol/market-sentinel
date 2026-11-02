# Why Market Sentinel exists — Crazy Investing portfolio context

**Status:** Operator-supplied working investment hypothesis, not a finalized investment policy, executed portfolio, performance claim, or authorization to trade.  
**Context date:** November 2, 2026.  
**Relationship to this repository:** Background rationale only. Market Sentinel's implemented features, boundaries, and commissioning rules remain governed by `README.md` and `AGENTS.md`.

## Objective and operating philosophy

The operator is exploring a **$1 million, multi-horizon income portfolio** intended to deliver **$10,000 monthly** while retaining long-term productive capital and market participation. Returns and distributions are irregular; the spending schedule is not.

> Time is invariant. Income delivery is scheduled. Capital becomes available in phases. Trading is discretionary. Ownership is deliberate. And the system is never finished.

The architecture is active and loss-aware, not built around a requirement to win every trade. Capital erosion can be tolerated and measured, but losses should **not** trigger mechanical increases in risk to restore a cash-flow target. The operator enjoys trading; the goal is to avoid **compulsory** trading, not minimize activity.

## Treasury maturity pipeline: $120,000

A rolling sequence of twelve approximately **$10,000 monthly T-bill maturities** delivers scheduled cash and absorbs timing shocks. Maturity proceeds, not investment earnings alone, fund the monthly withdrawal. Available portfolio cash flow replenishes the far end of the ladder; strong months can finance multiple new rungs, weak months none. The intended operating position is twelve funded months, though gaps and declining runway must be observable.

Cash used to refill rungs can arise from dividends, covered-call or put premiums, interest, structured-note coupons, private investment distributions, realized gains, and phased release of principal. These are **not equivalent economic returns**: distinguish true earnings, realized gains, and returned capital. Treasury interest offsets some replenishment needs. Meeting $120,000 annually is a cash-flow requirement, **not** evidence of a sustainable 12% total return.

## Allocation hypotheses — evolution, not ratification

| Sleeve | Parent-thread proposal | November 2 working alternative |
| --- | ---: | ---: |
| 12-month T-bill pipeline | $120,000 | $120,000 |
| Long-duration / relatively illiquid investments | ~$500,000 | ~$489,982 |
| Public equity + options | ~$380,000 | ~$390,018 |
| Total | $1,000,000 | $1,000,000 |

The **earlier** $380,000 tactical proposal was approximately **60% SPY ($228k)** and **40% individual Dividend Aristocrats ($152k)**, initially around nine positions, with fully paid shares, cash-secured puts, and no dependence on margin borrowing.

The **later** alternative prices **100 shares of each of 19 followed Aristocrats** at about **$390,018** using November 2 quotes. Those exact-lot weights are unequal: more expensive shares command larger allocations, which creates capital quantization and concentration concerns. This is a **hypothetical purchase cost**, not evidence the operator owns the basket. The remaining ~$490k could support public/private equity, credit, private placements, real estate, structured income notes, and vehicles such as ORENT. The earlier private layer contemplated 1–10-year phased liquidity; the precise holdings, timing, and equity/credit mix remain unresolved.

The benchmark is not asserted to be fully funded in this form. Legacy holdings are separate. Retirement-account access, SSDI outcomes, private-placement maturities, and property dispositions can affect the implementation timetable.

## Asymmetric Dividend Aristocrats options lifecycle

**Acquisition:** An oversold **RSI(14) or Stochastic(14,3,3)** observation can prompt manual evaluation of a near-ATM, roughly **50-delta cash-secured put**. Assignment is *desirable* if the underlying is worth owning; the premium lowers the effective acquisition cost. Expiration without assignment is acceptable. Technical signals alone do not establish fair valuation or ownership suitability. The parent proposal refers to crossings below 20; the operator also manually investigates RSI near 30–40. These should not be silently treated as the same signal or an implemented Sentinel requirement.

**Ownership:** After acquisition, retain the shares for long-term dividends and appreciation. Consider **far-OTM covered calls**, originally biased toward ~10–15 delta and now often examined around **16 delta**, to produce incremental premium without deliberately seeking call-away. Calls are optional: skip a cycle when bids are unattractive. Rolls are discretionary, can be costly, and cannot guarantee prevention of assignment; giving up upside or shares is an economic tradeoff, not just a fill-quality question. This is **not** the Income Wheel's routine weekly liquidation/redeployment regime.

Long-term stock selection and portfolio sector/industry concentration are external portfolio decisions. A high premium yield is not permission to overconcentrate. Wheelwright evaluates option overlays; Market Sentinel supplies technical attention signals rather than stock valuations or trade authorization.

## Research context as of November 2

A prior 70-name options study narrowed to a conditional 19-name subset and evaluated approximately 45-DTE calls around 10/15/20 delta. Farther-OTM calls gave up substantial premium; ~15 delta looked like an execution compromise, **not** a proven optimal policy. Dividend-adjusted delta, strike spacing, ex-dividend dates, call-away, rolls, and lost appreciation require care.

A subsequent **live production Tradier audit** on November 2, 2026, **14:37–14:44 EST**, collected **668 successful responses** covering 70 Aristocrats and SPY, preserved raw observations/hashes, and passed **134 offline tests**. At 46 DTE, **69/70** names showed two-sided ATM puts and **61/70** selected covered calls. ATM-put execution leaders: **KO, XOM, CVX, WMT, NEE**; covered-call leaders: **PEP, MCD, XOM, WMT, PG**. Across 61 comparable names the pooled live ±16-delta relative-spread median was **29.0%**, versus a **59.4%** earlier figure, but differing sources/models/periods mean the original quotes were not disproven. Quote-based bid premiums and spread estimates are **not verified fills or evidence of reliable repeatable income**. Local audit research SHA: `3069c031962ea20c4f948cddd0d6463df6caf0ce` (reported as local; remote main then unchanged).

Manual chain inspection also found usable ATM put and ~16-delta call strikes for names such as **ADM**, and plausible routine covered calls for **TGT** and **SHW**. Open interest and displayed quotes establish some participation, not guaranteed fills. Wide **relative** spreads can entail small absolute dollars for a single-lot, low-turnover owner. Bid-based income economics may matter more than squeezing midpoint fills, while a threatened call's buyback/roll liquidity can matter much more. Earnings, volatility regime, valuation, and sector overlap prevent treating these observations as strategy validation.

## What Sentinel is—and is not

Market Sentinel is an **independent attention mechanism** that monitors a configured equity universe for technical-indicator signals and produces informational reports/notifications for **manual review**. It exists because the investment architecture benefits from disciplined observation and opportunistic decision-making, without turning the Treasury schedule into forced trading. It **does not trade, authorize trades, select securities for ownership, guarantee income, or operate Wheelwright**. This context document commissions **no** RSI implementation, added provider calls, options-chain screen, trading logic, or portfolio subsystem.

## Unresolved portfolio research

- Can the coordinated sleeves replenish ~$120,000 per year over long periods without unacceptable capital erosion?
- What proportions come from earned income versus gains and released principal, after costs and taxes?
- Does oversold-signal ATM put acquisition improve outcomes relative to outright ownership?
- Does the ~10–16-delta covered-call overlay improve net total ownership economics after dividends, call-away, lost appreciation, and rolling?
- How much concentration results from 100-share contract sizing, sector overlap, and correlated risks?
- What happens if ladder runway shrinks during prolonged adverse markets or private distributions are delayed?

**Authority boundary:** These questions are portfolio hypotheses, not instructions to alter Sentinel's fixed universe, indicators, alert semantics, or technical architecture.
