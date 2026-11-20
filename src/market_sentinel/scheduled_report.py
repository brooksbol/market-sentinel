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


def due_previews(now, activated, sessions):
    """Only today's active close-minus-30m slot; no historical preview catch-up."""
    local = now.astimezone(ET)
    day = local.date()
    hours = sessions.get(str(day))
    if day < activated or not hours: return []
    closing = datetime.combine(day,time.fromisoformat(hours['end']),ET)
    due = closing-timedelta(minutes=30)
    opening = datetime.combine(day,time.fromisoformat(hours['start']),ET)
    if not max(due,opening) <= local < closing: return []
    return [dict(id=f'{day}:preclose',observation=str(day),kind='preclose',session=str(day),
                 due=due.isoformat(),expires=closing.isoformat())]


class PreviewExpired(Exception):
    """Known no-send outcome: preview deadline elapsed before HTTP began."""


def guard_preview(slot, clock):
    if clock() >= datetime.fromisoformat(slot['expires']): raise PreviewExpired()


def expire_previews(state, now):
    for item in state['deliveries'].values():
        if (item.get('kind')=='preclose' and item.get('status')=='waiting' and
                now >= datetime.fromisoformat(item['expires'])):
            item.update(status='expired',expired=now.isoformat(),reason='Scheduled close reached; preview suppressed.')


def screening_result(cutoff, results):
    valid = [row for row in results if row["status"] in ("calculated", "calculated_with_warnings")]
    warnings = sum(row["warning_count"] for row in valid)
    return dict(label=LABEL, notice=NOTICE, evidence_timestamp=datetime.now(timezone.utc).isoformat(),
                calculation_policy=dict(completed_exchange_sessions=HISTORY_SESSIONS,
                                        basis="Recent contiguous sessions; TA-Lib STOCH(14,3,3) SMA"),
                summary=dict(provider="Tradier", environment="production", completed_session=str(cutoff),
                             configured_symbols=len(SYMBOLS), acquired_symbols=len(valid),
                             evaluated_symbols=len(valid), usable_latest_symbols=len(valid),
                             new_downward_crossings=sum(row["latest"]["crossed_below_20"] for row in valid),
                             warning_count=warnings, status="incomplete" if len(valid) != len(SYMBOLS)
                             else "complete_with_warnings" if warnings else "complete"), results=results)


def failed_symbol(symbol, error, *, attempted=True):
    reason = safe_failure(error)
    kind = ("quota" if "rate limit" in reason or "quota" in reason.lower() else
            "access" if "authentication" in reason or "entitlement" in reason or "credentials" in reason else
            "network" if "network" in reason or "timeout" in reason else
            "history" if type(error) in (ScheduleError, TradierError) else "calculation")
    return dict(symbol=symbol, status="failed" if attempted else "not attempted after access/quota failure",
                error=reason, failure_kind=kind, attempted=attempted,
                evidence_timestamp=datetime.now(timezone.utc).isoformat())


def acquire_screening(token, cutoff, sessions, previous=None):
    """Retain verified same-slot observations; fetch only unresolved symbols.

    One symbol cannot abort its peers. Access/quota failures stop further requests.
    The caller validates the persisted snapshot identity before supplying previous.
    """
    cached = {row["symbol"]: row for row in previous["results"]} if previous else {}
    expected = tuple(date.fromisoformat(day) for day, hours in sorted(sessions.items())
                     if hours is not None and day <= str(cutoff))[-HISTORY_SESSIONS:]
    context_error = None
    if len(expected) != HISTORY_SESSIONS or expected[-1] != cutoff:
        context_error = ScheduleError("Insufficient verified historical calendar coverage.")
    elif any(str(expected[0]+timedelta(days=n)) not in sessions for n in range((cutoff-expected[0]).days+1)):
        context_error = ScheduleError("Incomplete recent exchange calendar.")
    results, stopped = [], None
    for symbol in SYMBOLS:
        prior = cached.get(symbol)
        if prior and prior["status"] in ("calculated", "calculated_with_warnings"):
            results.append(prior)
            continue
        if stopped is not None:
            results.append(failed_symbol(symbol, stopped, attempted=False))
            continue
        try:
            if context_error: raise context_error
            if isinstance(token, Exception): raise token
            history = fetch_history(token, symbol=symbol, environment="production", start=expected[0],
                                    end=cutoff, completed_through=cutoff, exclude_older=True)
            if tuple(bar.session for bar in history.bars) != expected:
                raise ScheduleError("Missing, stale or unexpected daily bars; symbol unavailable.")
            report = history_report(history)
            report["continuity"] = "Verified against Tradier regular-session calendar"
            if report["status"] not in ("calculated", "calculated_with_warnings"):
                raise ScheduleError("Unavailable indicator/comparison; symbol unavailable.")
            if report.get("symbol") != symbol:
                raise ScheduleError("Calculated symbol identity mismatch.")
            check = [report] + [dict(symbol=other, status="failed") for other in SYMBOLS if other != symbol]
            format_daily_report(screening_result(cutoff, check), compact=True)
            report["evidence_timestamp"] = datetime.now(timezone.utc).isoformat()
            results.append(report)
        except Exception as error:
            results.append(failed_symbol(symbol, error, attempted=not isinstance(token, Exception)))
            if (isinstance(error, TradierError) and error.stop_batch) or isinstance(token, Exception):
                stopped = error
    return screening_result(cutoff, results)


def notification_body(screening, slot, *, recovery=False):
    """One all-symbol snapshot; unknown evaluations never count as no signal."""
    if slot.get('kind') == 'preclose':
        from market_sentinel.preclose import message
        return message(screening,slot)
    if screening.get("summary", {}).get("completed_session") != slot["session"]:
        raise ScheduleError("Report session does not match the scheduled completed-session target.")
    prefix = "UPDATE " if recovery else ""
    body = f"{prefix}{slot['kind'].capitalize()} {slot['observation']} ET\n" + format_daily_report(screening, compact=True)
    if screening["summary"]["usable_latest_symbols"] < len(SYMBOLS):
        kinds = sorted({row.get("failure_kind", "unavailable") for row in screening["results"] if "latest" not in row})
        body += "\nReasons: " + ",".join(kinds)
        if screening["summary"]["usable_latest_symbols"] == 0:
            first = screening["results"][0]
            body += "\nFirst failure: " + first["symbol"] + ": " + first.get("error", "Unavailable")[:110]
        unattempted = [row["symbol"] for row in screening["results"] if row.get("attempted") is False]
        if unattempted: body += "\nNot requested: " + ",".join(unattempted)
        body += "\nRecovery: retry missing in 15m; one full update."
    elif recovery:
        body += "\nRecovery complete for original slot."
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
        if item.get("status") not in ("accepted", "attempting", "unknown", "waiting", "expired"):
            raise ScheduleError("Invalid delivery status; operator inspection required.")
    for identity, item in state["deliveries"].items():
        if item.get('status')=='expired' and item.get('kind')!='preclose':
            raise ScheduleError('Invalid expired completed-report status; operator inspection required.')
        if "recovery" in item:
            recovery = item["recovery"]
            if (not isinstance(recovery, dict) or recovery.get("id") != identity + ":recovery" or
                    recovery.get("status") not in ("waiting", "attempting", "accepted", "unknown", "expired")):
                raise ScheduleError("Invalid recovery ledger; operator inspection required.")
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


def progress_path(root, slot):
    return root / (slot["id"].replace(":", "-") + "-progress.json")


def read_progress(root, slot):
    path = progress_path(root, slot)
    if not path.exists(): return None
    report = json.loads(path.read_text())
    target = 'provisional_session' if slot.get('kind')=='preclose' else 'completed_session'
    if report.get("slot_id") != slot["id"] or report.get("summary", {}).get(target) != slot["session"]:
        raise ScheduleError("Progress evidence does not match this slot/session; operator inspection required.")
    if slot.get('kind')=='preclose':
        from market_sentinel.preclose import validate
        validate(report,slot)
    else:
        format_daily_report(report, compact=True)  # Validate every retained row before reuse.
    return report


def retain_snapshot(root, slot, report, *, recovery=False):
    name = slot["id"].replace(":", "-") + ("-recovery" if recovery else "")
    path = root / (name + ".json")
    if path.exists() and json.loads(path.read_text()) != report:
        # Previously retained evidence, including pre-upgrade evidence, is immutable.
        path = root / (name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
    if not path.exists(): save_json(path, report)
    return path.name


def unresolved(report):
    return [row["symbol"] for row in report["results"] if row["status"] not in ("calculated", "calculated_with_warnings")]


def task_entry(state, slot):
    record = state["deliveries"].get(slot["id"], {})
    return record.get("recovery", {}) if slot.get("recovery_update") else record


def current_failure(state):
    failures = []
    for item in state["deliveries"].values():
        if item.get("status") == "waiting" and item.get("last_failure"):
            failures.append(item["last_failure"])
        recovery = item.get("recovery", {})
        if recovery.get("status") == "waiting":
            failure = recovery.get("last_failure", item.get("last_failure"))
            if failure: failures.append(failure)
    return max(failures, key=lambda item: datetime.fromisoformat(item["at"]).timestamp()) if failures else None


def run_once(root, now=None, *, clock=None):
    """One eligible acquisition per tick; failed slots have independent backoff.

    Never-attempted slots precede retries, then oldest last acquisition first.
    Accepted/unknown report and operational-alert sends never automatically resend.
    """
    clock = clock or ((lambda: now) if now is not None else (lambda: datetime.now(timezone.utc)))
    now = now or clock()
    with (root / "worker.lock").open("a") as lock:
        os.chmod(root / "worker.lock", 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        state = read_state(root)
        interrupted = False
        for record in list(state["deliveries"].values()) + list(state.get("calendar_failures", {}).values()):
            for intent in (record, record.get("recovery", {})):
                if intent.get("status") == "attempting":
                    intent["status"] = "unknown"
                    interrupted = True
            alert = record.get("failure_alert", {})
            if alert.get("status") == "attempting":
                alert["status"] = "unknown"
                interrupted = True
        if interrupted:
            save_json(root / "state.json", state)
            log(root, now, "Previous notification intent interrupted; acceptance unknown. No automatic retry.")
        expire_previews(state,clock())
        if state.get("retry_scope") == "calendar" and now.timestamp() < state.get("retry_after", 0):
            save_json(root / "state.json",state)
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
            due = due_reports(now, activated, sessions) + due_previews(now,activated,sessions)
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
        newest = {kind: max((slot["observation"] for slot in due if slot["kind"] == kind), default="")
                  for kind in ("opening", "closing")}
        for slot in due:
            delivered = state["deliveries"].get(slot["id"], {})
            recovery = delivered.get("recovery", {})
            if recovery.get("status") == "waiting" and slot["observation"] < newest[slot["kind"]]:
                recovery.update(status="expired", expired=now.isoformat(),
                                reason="Newer " + slot["kind"] + " report is due; old recovery suppressed.")
                log(root, now, recovery["reason"], recovery["id"])
            if delivered.get("status") == "accepted":
                if recovery.get("status") == "waiting":
                    pending.append(dict(slot, recovery_update=True))
            elif delivered.get("status") not in ("unknown", "expired"):
                pending.append(slot)
        # Preserve a legacy pre-send failure/backoff without replaying any send.
        if pending and state.get("retry_scope") != "calendar" and state.get("retry_after", 0):
            first = pending[0]
            record = state["deliveries"].setdefault(first["id"], dict(first, status="waiting"))
            record.setdefault("retry_after", state["retry_after"])
            if state.get("last_failure"):
                record.setdefault("last_failure", state["last_failure"])
                record.setdefault("last_attempt", state["last_failure"]["at"])
        state.update(retry_after=0, retry_scope="calendar", last_check=now.isoformat())
        state["last_failure"] = current_failure(state)
        eligible = [slot for slot in pending if now.timestamp() >= task_entry(state, slot).get("retry_after", 0)]
        if not eligible:
            save_json(root / "state.json", state)
            return 0
        def priority(item):
            attempted = task_entry(state, item).get("last_attempt")
            return (0 if item.get('kind')=='preclose' else 1,
                    datetime.fromisoformat(attempted).timestamp() if attempted else float("-inf"), item["due"])
        slot = min(eligible, key=priority)
        parent = state["deliveries"].setdefault(slot["id"], dict(slot, status="waiting"))
        recovering = bool(slot.get("recovery_update"))
        record = parent["recovery"] if recovering else parent
        record["last_attempt"] = now.isoformat()
        identity = record.get("id", slot["id"])
        preview = slot['kind']=='preclose'
        try:
            if preview: guard_preview(slot,clock)
            previous = None if preview else read_progress(root, slot)
            if recovering and previous is None:
                raise ScheduleError("Recovery progress evidence missing; retained results cannot be substituted.")
            if previous and not unresolved(previous):
                screening = previous
            else:
                try:
                    token = token or load_token("production")
                except Exception:
                    token = TradierError("Market-data credentials unavailable; no history requested.", stop_batch=True)
                if preview:
                    from market_sentinel.preclose import acquire
                    screening = acquire(token,slot,sessions,clock)
                elif previous is None:
                    screening = acquire_screening(token, date.fromisoformat(slot["session"]), sessions)
                else:
                    screening = acquire_screening(token, date.fromisoformat(slot["session"]), sessions, previous=previous)
            if preview: guard_preview(slot,clock)
            screening["slot_id"] = slot["id"]
            body = notification_body(screening, slot, recovery=recovering)
            missing = unresolved(screening)
            record["unresolved_symbols"] = missing
            save_json(progress_path(root, slot), screening)
            if missing:
                reason = "; ".join(row["symbol"] + ": " + row.get("error", "Unavailable")
                                   for row in screening["results"] if row["symbol"] in missing)
                record["last_failure"] = dict(at=now.isoformat(), status=reason)
                state["last_failure"] = record["last_failure"]
                log(root, now, f"{len(SYMBOLS)-len(missing)}/19 available; " + reason, identity)
            if recovering and missing:
                record.update(retry_after=now.timestamp() + RETRY_SECONDS,
                              failure_count=record.get("failure_count", 0) + 1)
                save_json(root / "state.json", state)
                return 0  # Retained progress, not another partial push or failure alert.
            record["evidence_file"] = retain_snapshot(root, slot, screening, recovery=recovering)
            app_token, user_key = load_credentials()
            if preview: guard_preview(slot,clock)
        except PreviewExpired:
            record.update(status='expired',expired=clock().isoformat(),reason='Scheduled close reached before HTTP; no preview sent.')
            save_json(root / 'state.json',state)
            log(root,clock(),record['reason'],identity)
            return 0
        except Exception as error:
            record.update(retry_after=now.timestamp() + RETRY_SECONDS,
                          failure_count=record.get("failure_count", 0) + 1)
            record["last_failure"] = dict(at=now.isoformat(), status=safe_failure(error) + " No report sent.")
            state["last_failure"] = record["last_failure"]
            save_json(root / "state.json", state)
            log(root, now, record["last_failure"]["status"], identity)
            # No redundant operational alert for symbol failures or accepted partials.
            if not recovering and not preview: failure_alert(root, state, record, identity, now)
            return 1
        record.update(status="attempting", attempted=now.isoformat(), retry_after=0,
                      available_symbols=len(SYMBOLS)-len(missing))
        save_json(root / "state.json", state)
        try:
            if preview:
                from market_sentinel.preclose import TITLE as preview_title
                _send_message(app_token,user_key,preview_title,body,monospace=True,
                              before_request=lambda:guard_preview(slot,clock))
            else:
                _send_message(app_token, user_key, TITLE, body, monospace=True)
        except PreviewExpired:
            record.update(status='expired',expired=clock().isoformat(),reason='Scheduled close reached before HTTP; no preview sent.')
            save_json(root / 'state.json',state)
            log(root,clock(),record['reason'],identity)
            return 0
        except Exception:
            record["status"] = "unknown"
            save_json(root / "state.json", state)
            log(root, now, "Push rejected or acceptance unknown; operator review required. No automatic retry.", identity)
            return 1
        record.update(status="accepted", accepted=datetime.now(timezone.utc).isoformat(),
                      characters=len(body), utf8_bytes=len(body.encode("utf-8")))
        if not recovering and missing and not preview:
            record["recovery"] = dict(id=slot["id"] + ":recovery", status="waiting",
                                      retry_after=now.timestamp()+RETRY_SECONDS,
                                      last_attempt=now.isoformat(), unresolved_symbols=missing)
        elif recovering or record.get("last_failure"):
            record["recovered"] = record["accepted"]
        state["last_failure"] = current_failure(state)
        save_json(root / "state.json", state)
        log(root, now, ("Recovery update" if recovering else "Market report") +
            f" {len(SYMBOLS)-len(missing)}/19 API accepted; phone receipt not confirmed.", identity)
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
