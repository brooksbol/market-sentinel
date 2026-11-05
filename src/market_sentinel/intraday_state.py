"""Small single-writer SQLite evidence ledger; independent of monitor/platform."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path



def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Ledger:
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('State path must not be a symlink.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.stat().st_mode & 0o077:
            raise ValueError('Use a dedicated private intraday state directory (0700).')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=1)
        self.db.execute('PRAGMA synchronous=FULL')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError('Unsupported intraday ledger version; no reset performed.')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, symbol TEXT, session TEXT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS latest(symbol TEXT PRIMARY KEY, body TEXT, degraded INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, symbol TEXT, session TEXT, body TEXT NOT NULL, policy TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(event TEXT PRIMARY KEY, status TEXT NOT NULL, at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS completions(symbol TEXT, session TEXT, body TEXT NOT NULL, PRIMARY KEY(symbol, session));
            CREATE TABLE IF NOT EXISTS completion_checks(symbol TEXT, session TEXT, checked TEXT, PRIMARY KEY(symbol, session));
            CREATE TABLE IF NOT EXISTS status(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, body TEXT NOT NULL);
            PRAGMA user_version=1;
        ''')

    def close(self):
        self.db.close()

    def evidence(self, body):
        raw = encoded(body)
        key = hashlib.sha256(raw.encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO evidence VALUES (?, ?)', (key, raw))
        return key

    def degraded(self, symbol):
        with self.db:
            self.db.execute('INSERT INTO latest VALUES (?, NULL, 1) ON CONFLICT(symbol) DO UPDATE SET degraded=1', (symbol,))

    def record(self, current, *, send=False):
        """Atomic observation/event/intent reservation, serialized across processes.

        Every transition remains immutable. Only the first downward event per
        symbol/session can reserve a send; previewed and gap-qualified entries
        consume that conservative budget too. Never replay old intent on restart.
        """
        from market_sentinel.intraday import transition
        raw = encoded(current)
        identity = hashlib.sha256(raw.encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT body, degraded FROM latest WHERE symbol=?', (current['symbol'],)).fetchone()
            previous = json.loads(row[0]) if row and row[0] else None
            if previous and previous['session'] != current['session']:
                previous = None
            from datetime import datetime
            if previous and datetime.fromisoformat(current['observed']) <= datetime.fromisoformat(previous['observed']):
                self.db.commit()
                return None
            event = transition(previous, current, gap=bool(row and row[1]))
            self.db.execute('INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?)',
                            (identity, current['symbol'], current['session'], raw))
            self.db.execute('INSERT INTO latest VALUES (?, ?, 0) ON CONFLICT(symbol) DO UPDATE SET body=excluded.body, degraded=0',
                            (current['symbol'], raw))
            if event:
                event_id = 'intraday:' + identity + ':' + event['type']
                seen = self.db.execute('SELECT 1 FROM events WHERE symbol=? AND session=? AND json_extract(body,\'$.type\')=\'entered_oversold\'',
                                       (current['symbol'], current['session'])).fetchone()
                policy = 'retained_transition'
                if event['type'] == 'entered_oversold':
                    policy = ('duplicate_session_suppressed' if seen else
                              'gap_suppressed' if event['qualification'] == 'observation_gap' else
                              'send_reserved' if send else 'preview_only')
                event['id'] = event_id
                self.db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?)',
                                (event_id, current['symbol'], current['session'], encoded(event), policy))
                if policy == 'send_reserved':
                    self.db.execute('INSERT INTO attempts VALUES (?, ?, ?)', (event_id, 'intent_uncertain', current['detected']))
                event['policy'] = policy
            self.db.commit()
            return event
        except BaseException:
            self.db.rollback()
            raise

    def outcome(self, event_id, status, at):
        if status not in ('api_accepted', 'acceptance_unknown'):
            raise ValueError('Invalid delivery outcome.')
        with self.db:
            self.db.execute('UPDATE attempts SET status=?, at=? WHERE event=? AND status=\'intent_uncertain\'', (status, at, event_id))

    def status(self, value):
        with self.db:
            previous = self.db.execute('SELECT body FROM status WHERE id=1').fetchone()
            if previous and 'last_successful_update' not in value:
                value['last_successful_update'] = json.loads(previous[0]).get('last_successful_update')
            self.db.execute('INSERT INTO status VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (encoded(value),))
            self.db.execute('INSERT INTO runs(body) VALUES (?)', (encoded(value),))

    def pending_completions(self):
        return self.db.execute('SELECT DISTINCT e.symbol, e.session FROM events e LEFT JOIN completions c ON c.symbol=e.symbol AND c.session=e.session LEFT JOIN completion_checks x ON x.symbol=e.symbol AND x.session=e.session WHERE c.symbol IS NULL AND json_extract(e.body,\'$.type\')=\'entered_oversold\' ORDER BY COALESCE(x.checked,\'\'), e.session, e.symbol LIMIT 19').fetchall()

    def completion_checked(self, symbol, session, at):
        with self.db:
            self.db.execute('INSERT INTO completion_checks VALUES (?, ?, ?) ON CONFLICT(symbol, session) DO UPDATE SET checked=excluded.checked', (symbol, session, at))

    def complete(self, symbol, session, evidence):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO completions VALUES (?, ?, ?)', (symbol, session, encoded(evidence)))


def read_view(path):
    """Read-only browser snapshot. Does not create missing state or acquire data."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return dict(status={'state': 'No intraday observations retained'}, latest=[], events=[])
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        db.execute('BEGIN')
        with db:
            status = db.execute('SELECT body FROM status WHERE id=1').fetchone()
            latest = [dict(observation=json.loads(body) if body else None, symbol=symbol, degraded=bool(gap))
                      for symbol, body, gap in db.execute('SELECT symbol, body, degraded FROM latest')]
            events = [dict(json.loads(body), policy=policy, delivery=delivery or 'No send attempted',
                           completed_result=json.loads(completion) if completion else None)
                      for body, policy, delivery, completion in db.execute('SELECT e.body, e.policy, a.status, c.body FROM events e LEFT JOIN attempts a ON a.event=e.id LEFT JOIN completions c ON c.symbol=e.symbol AND c.session=e.session ORDER BY e.rowid DESC LIMIT 100')]
            return dict(status=json.loads(status[0]) if status else {}, latest=latest, events=events)
    finally:
        db.close()
