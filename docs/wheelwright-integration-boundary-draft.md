# Market Sentinel / Wheelwright Integration Boundary (Draft)

**Status:** Working architectural hypothesis — not ratified Product or engineering authority.  
**Date:** 2026-11-04  
**Scope:** Cross-repository integration; no change to existing implementations implied.

## Principle

> Wheelwright establishes the authoritative meaning and qualified results of capabilities it explicitly owns; external systems remain the origin of their own state. Market Sentinel governs application-specific analytics, attention, and delivery. Integration occurs through published contracts, never through competing implementations of the same governed capability.

Ownership is explicit, not inferred merely because a capability involves financial information.

## Responsibilities

**Wheelwright — governed financial capabilities (where established by its own Product authority):**
- Brokerage account and position identity and authorization
- Options chains, Greeks, and governed spread economics
- Financial evidence semantics, qualification, and governed eligibility constraints
- Published interfaces that preserve those semantics for consumers

**Market Sentinel — application intelligence:**
- Its independently owned technical indicators (currently Stochastic 14-3-3) and associated market observations
- Attention scoring and operator-specific prioritization
- Report composition, scheduling, notifications, duplicate suppression, and delivery history

Market Sentinel may prioritize an oversold instrument for attention without asserting that it is financially eligible, that its options economics are qualified, or that a trade is authorized. Attention ordering does not redefine Wheelwright financial eligibility or governed comparative ranking; new scoring is separately commissioned. **Attention decisions are not trading or execution decisions.**

## Cross-repository contract

For each shared capability, distinguish:

1. **Capability ownership:** Who establishes the calculation or result and its authoritative meaning?
2. **Evidence ownership:** Who supplies observations, timestamps, qualification, and provenance?
3. **Decision ownership:** Who decides whether a result deserves attention, qualifies under financial constraints, or may be acted upon?

These may differ. Consumers must preserve identity, qualification, and provenance, and must not silently substitute incomplete evidence for qualified results.

Market Sentinel consumes Wheelwright-governed capabilities **only through published Wheelwright interfaces**. It must not directly reproduce or bypass their domain logic, identity, evidence, or authorization boundaries. Market Sentinel may independently acquire market observations for explicitly owned capabilities such as Stochastic analytics, provided doing so does not circumvent Wheelwright authority.

A working internal Wheelwright tool is not automatically a supported published contract. Reusable interfaces need sufficient discoverability, versioning, and semantics for consumers, but publication should not require a heavyweight governance framework.

## Example

Market Sentinel flags an oversold Dividend Aristocrat using its Stochastic signal. If available, it composes that signal with Wheelwright-provided, qualified options liquidity and spread-economics results. Wheelwright establishes what its financial results mean; Market Sentinel determines why the operator might look today. Neither notification nor ranking authorizes a trade.

## Review and status

This is a **draft working principle**, not ratified authority or a mandate to migrate the existing Tradier-backed Stochastic pipeline. It proposes a **mandatory** architectural boundary for any future Wheelwright-governed integration: published Wheelwright interfaces are the only permitted integration path. It establishes no immediate integration requirement and does not change Market Sentinel's current independent operating scope. Review current authority independently in both repositories and identify only material contradictions or minimal changes needed to formalize the boundary. Consider the TT1 exporter as a concrete example of the separate internal-tool-to-published-capability question. Do not expand the scope into an ADR registry, governance process, framework, or implementation plan.
