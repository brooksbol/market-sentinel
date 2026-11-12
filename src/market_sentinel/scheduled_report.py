"""Local opening/closing universe reports. No actionable alerts or trading.

launchd only invokes this worker. Eastern-time session selection, protected
atomic delivery ledger and acquisition checks live here, apart from pure math.
"""

import calendar
import fcntl
import json
import os
import plistlib
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from market_sentinel.daily_report import TITLE, format_daily_report
from market_sentinel.pushover import _send_message, load_credentials, validate_message
from market_sentinel.tradier import TradierError, _get_json, fetch_history, load_token
from market_sentinel.tradier_report import LABEL, NOTICE, history_report
from market_sentinel.universe import SYMBOLS

ET = ZoneInfo("America/New_York")
LABEL_JOB = "com.market-sentinel.daily-reports"
RUNTIME = Path.home() / "Library/Application Support/Market Sentinel/automatic-reports"
RETRY_SECONDS = 900
# STOCH(14,SMA3,SMA3) lookback 17, plus two adjacent available K/D points.
HISTORY_SESSIONS = 19
FAILURE_TITLE = "Market Sentinel: report unavailable"


class ScheduleError(ValueError):
    """Safe operational diagnostic; never contains provider responses or secrets."""


def normalize_calendar(payload, year, month):
    """Require every calendar day, explicit open/closed and valid regular hours."""
    try:
        body = payload["calendar"]
        rows = body["days"]["day"]
        if body["year"] != year or body["month"] != month or not isinstance(rows, list):
            raise ValueError
        result = {}
        for row in rows:
            day = date.fromisoformat(row["date"])
            if str(day) != row["date"] or (day.year, day.month) != (year, month) or str(day) in result:
                raise ValueError
            if row["status"] == "closed":
                result[str(day)] = None
            elif row["status"] == "open":
                start, end = row["open"]["start"], row["open"]["end"]
                opening, closing = time.fromisoformat(start), time.fromisoformat(end)
                if (day.weekday() >= 5 or opening.tzinfo or closing.tzinfo or
                        opening >= closing or start != opening.strftime("%H:%M") or end != closing.strftime("%H:%M")):
                    raise ValueError
                result[str(day)] = {"start": start, "end": end}
            else:
                raise ValueError
        expected = {str(date(year, month, d)) for d in range(1, calendar.monthrange(year, month)[1] + 1)}
        if set(result) != expected:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ScheduleError("Incomplete or invalid Tradier market calendar; no session assumed.") from None


def due_reports(now, activated, sessions):
    """Chronological slots: open+1 minute and close+1; early closes follow calendar.

    Morning always uses the previous completed regular session. No current-session
    prices can leak into it, including a delayed morning invocation after close.
    """
    if now.tzinfo is None:
        raise ScheduleError("An aware clock is required.")
    local = now.astimezone(ET)
    previous, due = None, []
    for identity, hours in sorted(sessions.items()):
        day = date.fromisoformat(identity)
        if hours is None:
            continue
        if activated <= day <= local.date():
            if previous is None:
                raise ScheduleError("Previous trading session is unavailable.")
            for kind, clock, target in (("opening", hours["start"], previous), ("closing", hours["end"], day)):
                at = datetime.combine(day, time.fromisoformat(clock), ET) + timedelta(minutes=1)
                if at <= local:
                    due.append(dict(id=f"{day}:{kind}", observation=str(day), kind=kind,
                                    session=str(target), due=at.isoformat()))
        previous = day
    return due


def acquire_screening(token, cutoff, sessions):
    """One GET per symbol; require exact exchange-calendar coverage before sending."""
    expected = tuple(date.fromisoformat(day) for day, hours in sorted(sessions.items())
                     if hours is not None and day <= str(cutoff))[-HISTORY_SESSIONS:]
    if len(expected) != HISTORY_SESSIONS or expected[-1] != cutoff:
        raise ScheduleError("Insufficient verified historical calendar coverage.")
    start = expected[0]
    if any(str(start + timedelta(days=n)) not in sessions for n in range((cutoff-start).days+1)):
        raise ScheduleError("Incomplete recent exchange calendar; report delayed.")
    results = []
    for symbol in SYMBOLS:
        try:
            history = fetch_history(token, symbol=symbol, environment="production", start=start,
                                    end=cutoff, completed_through=cutoff, exclude_older=True)
        except TradierError as error:
            raise ScheduleError(symbol + ": " + str(error)) from None
        if tuple(bar.session for bar in history.bars) != expected:
            raise ScheduleError("Missing, stale or unexpected daily bars for " + symbol + "; report delayed.")
        report = history_report(history)
        report["continuity"] = "Verified against Tradier regular-session calendar"
        if report["status"] not in ("calculated", "calculated_with_warnings"):
            raise ScheduleError("Unavailable indicator/comparison for " + symbol + "; report delayed.")
        results.append(report)
    warnings = sum(row["warning_count"] for row in results)
    return dict(label=LABEL, notice=NOTICE, evidence_timestamp=datetime.now(timezone.utc).isoformat(),
                calculation_policy=dict(completed_exchange_sessions=HISTORY_SESSIONS,
                                        basis="Recent contiguous sessions; TA-Lib STOCH(14,3,3) SMA"),
                summary=dict(provider="Tradier", environment="production", completed_session=str(cutoff),
                             configured_symbols=19, acquired_symbols=19, evaluated_symbols=19, usable_latest_symbols=19,
                             new_downward_crossings=sum(row["latest"]["crossed_below_20"] for row in results),
                             warning_count=warnings, status="complete_with_warnings" if warnings else "complete"),
                results=results)


def notification_body(screening, slot):
    """Add observation context; report itself labels the completed data session."""
    if screening.get("summary", {}).get("completed_session") != slot["session"]:
        raise ScheduleError("Report session does not match the scheduled completed-session target.")
    body = f"{slot['kind'].capitalize()} {slot['observation']} ET\n" + format_daily_report(screening)
    validate_message(TITLE, body)
    return body


def save_json(path, value):
    """Atomic protected file, including fsync before replacement."""
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_state(root):
    state = json.loads((root / "state.json").read_text())
    # Refuse corruption rather than reset history and duplicate accepted pushes.
    if (state.get("version") != 1 or not isinstance(state.get("deliveries"), dict) or
            not isinstance(state.get("calendars"), dict) or
            str(date.fromisoformat(state["activated"])) != state["activated"]):
        raise ScheduleError("Invalid delivery ledger; operator inspection required.")
    for item in state["deliveries"].values():
        if item.get("status") not in ("accepted", "attempting", "unknown", "waiting"):
            raise ScheduleError("Invalid delivery status; operator inspection required.")
    if not isinstance(state.get("calendar_failures", {}), dict):
        raise ScheduleError("Invalid calendar failure ledger; operator inspection required.")
    for item in list(state["deliveries"].values()) + list(state.get("calendar_failures", {}).values()):
        if "failure_alert" in item:
            alert = item["failure_alert"]
            if not isinstance(alert, dict) or alert.get("status") not in ("accepted", "attempting", "unknown", "waiting"):
                raise ScheduleError("Invalid operational alert status; operator inspection required.")
    return state


def log(root, now, status, slot=None):
    # Bounded, sanitized structured diagnostics. No caught exception text is logged.
    path = root / "worker.log"
    if path.exists() and path.stat().st_size > 524288:
        os.replace(path, root / "worker.previous.log")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a") as stream:
        stream.write(json.dumps(dict(at=now.isoformat(), status=status, slot=slot)) + "\n")


def safe_failure(error):
    return (str(error) if type(error) in (ScheduleError, TradierError)
            else "Acquisition/calendar/credentials/preflight failure; details suppressed.")


def failure_alert(root, state, record, identity, now):
    """One operational alert per report slot (calendar failures: one per ET day).

    Credential/preflight failures are safe to retry on the next acquisition retry.
    Persist intent before HTTP; accepted/unknown/interrupted alerts never resend.
    A recovered market report is the recovery notification, not another alert.
    """
    alert = record.setdefault("failure_alert", {})
    if alert.get("status") == "attempting":
        alert["status"] = "unknown"
        save_json(root / "state.json", state)
    if alert.get("status") in ("accepted", "unknown"):
        return
    body = (f"Report unavailable: {identity} ET\n"
            + record["last_failure"]["status"][:600]
            + "\nAcquisition retries every 15 minutes; other eligible slots continue."
              " No market report was sent for this attempt.")
    try:
        validate_message(FAILURE_TITLE, body)
        app_token, user_key = load_credentials()
    except Exception:
        alert.update(status="waiting", last_check=now.isoformat(),
                     reason="Operational alert credentials/preflight unavailable; no send attempted.")
        save_json(root / "state.json", state)
        log(root, now, alert["reason"], identity)
        return
    alert.update(status="attempting", attempted=now.isoformat())
    save_json(root / "state.json", state)
    try:
        _send_message(app_token, user_key, FAILURE_TITLE, body, monospace=False)
    except Exception:
        alert["status"] = "unknown"
        log(root, now, "Operational alert acceptance unknown; no automatic resend.", identity)
    else:
        alert.update(status="accepted", accepted=datetime.now(timezone.utc).isoformat())
        log(root, now, "Operational alert API accepted; phone receipt not confirmed.", identity)
    save_json(root / "state.json", state)


def run_once(root, now=None):
    """One eligible acquisition per tick; failed slots have independent backoff.

    Never-attempted slots precede retries, then oldest last acquisition first.
    Accepted/unknown report and operational-alert sends never automatically resend.
    """
    now = now or datetime.now(timezone.utc)
    with (root / "worker.lock").open("a") as lock:
        os.chmod(root / "worker.lock", 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        state = read_state(root)
        interrupted = False
        for record in list(state["deliveries"].values()) + list(state.get("calendar_failures", {}).values()):
            alert = record.get("failure_alert", {})
            if alert.get("status") == "attempting":
                alert["status"] = "unknown"
                interrupted = True
        if interrupted:
            save_json(root / "state.json", state)
            log(root, now, "Previous operational alert interrupted; acceptance unknown. No automatic retry.")
        if state.get("retry_scope") == "calendar" and now.timestamp() < state.get("retry_after", 0):
            return 0
        try:
            today = now.astimezone(ET).date()
            activated = date.fromisoformat(state["activated"])
            # Complete months supply catch-up slots and the 19-session window.
            first = activated - timedelta(days=90)
            month = date(first.year, first.month, 1)
            token = None
            while month <= today:
                key = month.strftime("%Y-%m")
                entry = state["calendars"].get(key)
                refresh = not entry or (month.year == today.year and month.month == today.month and entry["checked"] != str(today))
                if refresh:
                    token = token or load_token("production")
                    days = normalize_calendar(_get_json(token, "production", "calendar", dict(year=month.year, month=month.month)),
                                              month.year, month.month)
                    state["calendars"][key] = dict(checked=str(today), days=days)
                month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            sessions = {day: hours for entry in state["calendars"].values() for day, hours in entry["days"].items()}
            due = due_reports(now, activated, sessions)
        except Exception as error:
            state.update(retry_after=now.timestamp() + RETRY_SECONDS, retry_scope="calendar")
            state["last_failure"] = dict(at=now.isoformat(), status=safe_failure(error) + " No report sent.")
            record = state.setdefault("calendar_failures", {}).setdefault(str(now.astimezone(ET).date()), {})
            record["last_failure"] = state["last_failure"]
            save_json(root / "state.json", state)
            log(root, now, state["last_failure"]["status"])
            # Cached calendar can identify the affected slots; never invent a session.
            try:
                cached = {day: hours for entry in state["calendars"].values() for day, hours in entry["days"].items()}
                identities = [slot["id"] for slot in due_reports(now, date.fromisoformat(state["activated"]), cached)
                              if state["deliveries"].get(slot["id"], {}).get("status") not in ("accepted", "unknown")]
            except Exception:
                identities = []
            failure_alert(root, state, record, ", ".join(identities)[:200] or "scheduled slots (calendar unavailable)", now)
            return 1
        pending = []
        for slot in due:
            delivered = state["deliveries"].get(slot["id"], {})
            if delivered.get("status") == "attempting":
                delivered["status"] = "unknown"
                log(root, now, "Previous send interrupted; acceptance unknown. No automatic retry.", slot["id"])
            if delivered.get("status") in ("accepted", "unknown"):
                continue
            pending.append(slot)
        # Preserve a legacy pre-send failure/backoff, but attach it to its slot.
        if pending and state.get("retry_scope") != "calendar" and state.get("retry_after", 0):
            record = state["deliveries"].setdefault(pending[0]["id"], dict(pending[0], status="waiting"))
            record.setdefault("retry_after", state["retry_after"])
            if state.get("last_failure"):
                record.setdefault("last_failure", state["last_failure"])
                record.setdefault("last_attempt", state["last_failure"]["at"])
        state.update(retry_after=0, retry_scope="calendar")
        state["last_check"] = now.isoformat()
        eligible = [slot for slot in pending if now.timestamp() >= state["deliveries"].get(slot["id"], {}).get("retry_after", 0)]
        if not eligible:
            save_json(root / "state.json", state)
            return 0
        def priority(item):
            attempted = state["deliveries"].get(item["id"], {}).get("last_attempt")
            return (datetime.fromisoformat(attempted).timestamp() if attempted else float("-inf"), item["due"])
        slot = min(eligible, key=priority)
        record = state["deliveries"].setdefault(slot["id"], dict(slot, status="waiting"))
        record["last_attempt"] = now.isoformat()
        try:
            token = token or load_token("production")
            screening = acquire_screening(token, date.fromisoformat(slot["session"]), sessions)
            body = notification_body(screening, slot)
            save_json(root / (slot["id"].replace(":", "-") + ".json"), screening)
            app_token, user_key = load_credentials()
        except Exception as error:
            record.update(retry_after=now.timestamp() + RETRY_SECONDS,
                          failure_count=record.get("failure_count", 0) + 1)
            record["last_failure"] = dict(at=now.isoformat(), status=safe_failure(error) + " No report sent.")
            state["last_failure"] = record["last_failure"]
            save_json(root / "state.json", state)
            log(root, now, record["last_failure"]["status"], slot["id"])
            failure_alert(root, state, record, slot["id"], now)
            return 1
        record.update(status="attempting", attempted=now.isoformat(), retry_after=0)
        save_json(root / "state.json", state)
        try:
            _send_message(app_token, user_key, TITLE, body, monospace=True)
        except Exception:
            record["status"] = "unknown"
            save_json(root / "state.json", state)
            log(root, now, "Push rejected or acceptance unknown; operator review required. No automatic retry.", slot["id"])
            return 1
        record.update(status="accepted", accepted=datetime.now(timezone.utc).isoformat(),
                      characters=len(body), utf8_bytes=len(body.encode("utf-8")))
        if record.get("last_failure"):
            record["recovered"] = record["accepted"]
        # Other blocked slots retain their own diagnostics even after this success.
        state["last_failure"] = next((item["last_failure"] for item in state["deliveries"].values()
                                      if item.get("status") == "waiting" and item.get("last_failure")), None)
        save_json(root / "state.json", state)
        log(root, now, "Pushover API accepted; phone receipt not confirmed.", slot["id"])
        return 0


def launch_agent(python, root, checkout):
    """Every minute while awake; missed calendar ticks coalesce on wake."""
    return dict(Label=LABEL_JOB, ProgramArguments=[str(python), "-m", "market_sentinel.scheduled_report", "--run"],
                WorkingDirectory=str(checkout), RunAtLoad=True,
                StartCalendarInterval=[dict(Minute=minute) for minute in range(60)],
                ProcessType="Background", Umask=0o077,
                StandardOutPath=str(root / "launchd.log"), StandardErrorPath=str(root / "launchd.log"))


def install(root=RUNTIME):
    """Explicit local activation, never overwrite an existing ledger/job."""
    if sys.platform != "darwin":
        raise ScheduleError("Local launchd activation requires macOS.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    plist_path = Path.home() / "Library/LaunchAgents" / (LABEL_JOB + ".plist")
    if (root / "state.json").exists() or plist_path.exists():
        raise ScheduleError("Existing installation preserved; inspect status instead of overwriting.")
    save_json(root / "state.json", dict(version=1, activated=str(datetime.now(ET).date()), deliveries={}, calendars={}))
    plist_path.parent.mkdir(exist_ok=True)
    checkout = Path(__file__).resolve().parents[2]
    with plist_path.open("wb") as stream:
        plistlib.dump(launch_agent(Path(sys.executable).absolute(), root, checkout), stream)
    os.chmod(plist_path, 0o600)
    result = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
                            capture_output=True, timeout=20)
    if result.returncode:
        raise ScheduleError("launchd bootstrap failed; installation files preserved for inspection.")
    print("LaunchAgent installed. Check status and provider acceptance; phone delivery is independent.")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if args == ["--install"]:
            install()
            return 0
        if args == ["--run"]:
            return run_once(RUNTIME)
        if args == ["--status"]:
            state = read_state(RUNTIME)
            print(json.dumps({k: state.get(k) for k in ("activated", "last_check", "last_failure", "retry_after", "retry_scope", "deliveries", "calendar_failures")}, indent=2))
            return 0
        print("Use --status, --run or explicitly authorized --install. No action taken.")
        return 2
    except Exception:
        print("Market Sentinel worker/installation failed; inspect protected state/logs. Details suppressed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
