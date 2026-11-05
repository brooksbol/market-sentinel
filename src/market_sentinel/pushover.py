"""A single, explicit Pushover transport test; no monitor or automatic retries."""

import json
import os
import re
import subprocess
import sys
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ENDPOINT = "https://api.pushover.net/1/messages.json"
TITLE = "Market Sentinel — Test"
MESSAGE = "Push transport verification. No market signal or trading action."
KEYCHAIN_SERVICE = "market-sentinel.pushover"
MAX_RESPONSE_BYTES = 16_384


class PushError(Exception):
    """Safe, operator-facing error; never includes provider bodies or secrets."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials must only be posted to the fixed HTTPS endpoint.
        return None


def _validate_credentials(token: str, user_key: str) -> None:
    if not all(re.fullmatch(r"[A-Za-z0-9]{30}", key) for key in (token, user_key)):
        raise PushError("Pushover credentials must each be 30 ASCII letters/digits.")


def load_credentials() -> tuple[str, str]:
    """Use a complete environment handoff, otherwise the operator's macOS Keychain.

    No interactive prompts, credential creation or raw subprocess output logging.
    Partial environment overrides are rejected to avoid mixing identities.
    """
    token = os.environ.get("PUSHOVER_APP_TOKEN")
    user_key = os.environ.get("PUSHOVER_USER_KEY")
    if token is not None or user_key is not None:
        if not token or not user_key:
            raise PushError("Set both PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY, or neither.")
    else:
        if sys.platform != "darwin":
            raise PushError("Supply both Pushover credentials through the environment.")
        values = []
        for account in ("application-token", "user-key"):
            try:
                result = subprocess.run(
                    ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                     "-a", account, "-w"],
                    capture_output=True, text=True, check=False, timeout=15,
                )
            except (OSError, subprocess.SubprocessError, UnicodeError):
                raise PushError("Unable to read Pushover credentials from macOS Keychain.") from None
            if result.returncode != 0:
                raise PushError("Pushover Keychain item unavailable; complete the README setup.")
            values.append(result.stdout.strip())
        token, user_key = values
    _validate_credentials(token, user_key)
    return token, user_key


def send_test_push(token: str, user_key: str) -> None:
    """Send exactly one request and return only after documented API acceptance.

    A timeout is ambiguous: Pushover may have accepted the request. No automatic
    retry is made, and no phone-delivery claim is inferred from API acceptance.
    """
    _send_message(token, user_key, TITLE, MESSAGE)


def validate_message(title: str, message: str) -> None:
    """Check decoded UTF-8 character limits, not percent-encoded POST size.

    Pushover permits 1024 Unicode characters (up to four UTF-8 bytes each).
    Python len counts code points, including combining marks separately. Reject
    invalid UTF-8/surrogates rather than replacing or truncating content.
    """
    if not isinstance(title, str) or not isinstance(message, str) or not message:
        raise PushError("A text title and nonempty message are required.")
    try:
        title.encode("utf-8")
        message.encode("utf-8")
    except UnicodeError:
        raise PushError("Notification contains invalid UTF-8 text.") from None
    if len(title) > 250 or len(message) > 1024:
        raise PushError("Pushover limit exceeded: title 250 characters, body 1024. Nothing sent.")


def _send_message(token: str, user_key: str, title: str, message: str, *, monospace: bool = False, before_request=None) -> None:
    """Shared private transport; callers own explicit authorization and payloads."""
    _validate_credentials(token, user_key)
    validate_message(title, message)
    fields = {"token": token, "user": user_key, "title": title, "message": message}
    if monospace:
        fields["monospace"] = "1"
    body = urlencode(fields, encoding="utf-8", errors="strict").encode("ascii")
    request = Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "User-Agent": "Market-Sentinel-Transport-Test/0.1",
    })
    # Direct HTTPS, normal certificate validation, no ambient proxy or redirects.
    opener = build_opener(ProxyHandler({}), _NoRedirects())
    if before_request is not None:
        before_request()  # Intraday deadline/freshness guard, after credential/request preparation.
    try:
        with opener.open(request, timeout=10) as response:
            status = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        if status in (400, 401, 403):
            raise PushError("Pushover rejected the credentials or request; check provider setup.") from None
        if status == 429:
            raise PushError("Pushover request quota exceeded; do not retry immediately.") from None
        raise PushError("Pushover HTTP failure; API acceptance was not established.") from None
    except (TimeoutError, URLError, OSError, HTTPException):
        raise PushError(
            "Network/TLS failure or timeout; API acceptance is unknown. "
            "Check the phone before authorizing another test."
        ) from None
    if status != 200 or len(raw) > MAX_RESPONSE_BYTES:
        raise PushError("Unexpected Pushover response; API acceptance was not established.")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise PushError("Invalid Pushover response; API acceptance was not established.") from None
    if not isinstance(payload, dict) or type(payload.get("status")) is not int:
        raise PushError("Invalid Pushover response; API acceptance was not established.")
    if payload["status"] != 1:
        raise PushError("Pushover rejected the request; check credentials and provider setup.")
