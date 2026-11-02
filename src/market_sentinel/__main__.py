"""Explicit command-line entry point for the bounded transport proof."""

import argparse
import sys

from market_sentinel.pushover import PushError, load_credentials, send_test_push


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid arguments, possibly pasted credentials.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command. Use --help; never pass credentials as arguments.\n")


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description="Market Sentinel transport proof; no market monitor.")
    commands = parser.add_subparsers(dest="command", required=True)
    push = commands.add_parser("push-test", help="send one explicitly authorized Pushover test")
    push.add_argument("--send", action="store_true", help="explicitly send the real test request")
    args = parser.parse_args(argv)
    if not args.send:
        print("No notification sent. After operator authorization, use push-test --send.")
        return 2
    try:
        token, user_key = load_credentials()
        send_test_push(token, user_key)
    except PushError as error:
        print(f"Test request failed: {error}", file=sys.stderr)
        return 1
    except Exception:
        # Last-resort CLI boundary: third-party/network exceptions can echo input.
        print("Test request failed unexpectedly; API acceptance is unknown. No details logged.",
              file=sys.stderr)
        return 1
    print("Pushover API accepted the test request. Phone delivery is NOT confirmed. "
          "Check your iPhone and independently confirm receipt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
