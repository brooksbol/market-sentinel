# Market Sentinel — coding instructions

This is an independent, small Python utility. It is not a Wheelwright component.
Read `README.md`, current code and relevant tests before changing behavior.

- Keep work within the current assignment. Do not add indicators, market data,
  persistence, scheduling or other subsystems before they are commissioned.
- Keep calculations deterministic and independent of acquisition, scheduling,
  persistence and notification transport. Preserve completed-session, full-precision
  crossing semantics and independent symbol/indicator event identities.
- Keep credentials, personal data, runtime databases and logs outside Git. Never
  print secrets or raw provider errors that could contain them. Use synthetic
  credentials in tests; do not retrieve the operator's real credentials for tests.
- Routine tests must be offline, with network and credential-store access mocked.
  Test behavioral changes and report actual results and limitations.
- A provider's API acceptance is not confirmed phone receipt. Live notification
  tests require explicit operator authorization after provider setup.
- Inspect Git status and remote state before edits and before publishing. Preserve
  unrelated work; commit small, reviewable changes and verify the remote result.
- Favor a few concrete functions over a general framework. Keep dependencies and
  documentation proportionate. Do not import Wheelwright governance or create
  roadmaps, ADR registries, parking lots, journals or multi-actor machinery without
  a demonstrated need and an explicit assignment.
