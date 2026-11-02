"""Exactly three fixed historical demonstration payloads; no monitoring or retries."""

import json
import sys
from datetime import datetime, timezone

from market_sentinel.__main__ import _SafeParser
from market_sentinel.pushover import PushError, _send_message, load_credentials

MESSAGES = (
    ("Market Sentinel — Oversold",
     "ADM — Stochastic %K 7.01, %D 5.80.\n\n"
     "Below the 20 threshold as of October 30, 2026.\n\n"
     "Informational screening observation. Not a new crossing or trading instruction.\n\n"
     "Demonstration using previously verified data."),
    ("Market Sentinel — Oversold",
     "CAT — Stochastic %K 12.69, %D 17.04.\n\n"
     "Below the 20 threshold as of October 30, 2026.\n\n"
     "Informational screening observation. Not a new crossing or trading instruction.\n\n"
     "Demonstration using previously verified data."),
    ("Market Sentinel — Daily Receipt TEST",
     "October 30, 2026\n\n"
     "19/19 symbols evaluated.\n"
     "New Stochastic crossings: 0.\n"
     "Current oversold observations: ADM, CAT.\n"
     "Data-quality warnings: 13 across the historical sample.\n\n"
     "Demonstration using previously verified data. Not a live scheduled monitoring result."),
)


def send_demonstration(token, user_key):
    """At most three requests per authorized invocation; stop on first error.

    Each fixed message is attempted once. Errors/timeouts are never retried.
    API acceptance is not independent confirmation of iPhone delivery.
    """
    results = []
    for index, (title, body) in enumerate(MESSAGES, 1):
        result = dict(message=index, title=title, attempted_at=datetime.now(timezone.utc).isoformat())
        try:
            _send_message(token, user_key, title, body)
        except PushError as error:
            result.update(status="failed_or_unknown", error=str(error))
        except Exception:
            result.update(status="failed_or_unknown", error="Unexpected failure; details suppressed. No retry.")
        else:
            result["status"] = "api_accepted"
        results.append(result)
        if result["status"] != "api_accepted":
            break
    results.extend(dict(message=i, status="not_attempted_after_failure")
                   for i in range(len(results)+1, len(MESSAGES)+1))
    return results


def main(argv=None):
    parser = _SafeParser(description="Three fixed historical demonstration pushes, never live screening.")
    parser.add_argument("--send", action="store_true", help="send up to three explicitly authorized real demonstrations")
    args = parser.parse_args(argv)
    if not args.send:
        print("No messages sent or credentials read. Separate operator authorization and --send are required.")
        return 2
    try:
        token, user_key = load_credentials()
    except PushError as error:
        print(f"Demonstration setup failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("Demonstration setup failed; details suppressed.", file=sys.stderr)
        return 1
    results = send_demonstration(token, user_key)
    print(json.dumps(dict(results=results, phone_receipt="NOT independently confirmed"), indent=2))
    return 0 if all(r["status"] == "api_accepted" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
