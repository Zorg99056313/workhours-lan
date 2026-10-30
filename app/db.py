# -*- coding: utf-8 -*-
"""SQLite 数据层：建表、连接、查询封装"""
import os
import sqlite3
import threading
from contextlib import contextmanager

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    job_title       TEXT    DEFAULT '',
    dept            TEXT    DEFAULT '',
    role            TEXT    NOT NULL DEFAULT 'member',   -- admin | member
    person_type     TEXT    NOT NULL DEFAULT '研发人员',   -- 研发人员 | 辅助人员
    password_hash   TEXT    NOT NULL,
    salt            TEXT    NOT NULL,
    week_quota      INTEGER NOT NULL DEFAULT 10,
    active          INTEGER NOT NULL DEFAULT 1,
    track_hours     INTEGER NOT NULL DEFAULT 1,           -- 是否参与工时统计
    must_change_pwd INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,
    ptype      TEXT    NOT NULL DEFAULT '研发',
    status     TEXT    NOT NULL DEFAULT '进行中',
    active     INTEGER NOT NULL DEFAULT 1,
    sort       INTEGER NOT NULL DEFAULT 0,
    remark     TEXT    DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    work_date     TEXT    NOT NULL,               -- YYYY-MM-DD
    seq           INTEGER NOT NULL DEFAULT 0,     -- 当天第几条明细（0 起）
    work_type     TEXT    NOT NULL,               -- 研发 | 非研发 | 休假
    work_kind     TEXT    NOT NULL DEFAULT '正常', -- 正常 | 加班（只做标记，统计口径同名）
    project_id    INTEGER,
    hours         REAL    NOT NULL DEFAULT 0,     -- 本条工时（小时，可小数）
    rd_hours      REAL    NOT NULL DEFAULT 0,
    nrd_hours     REAL    NOT NULL DEFAULT 0,
    content       TEXT    NOT NULL DEFAULT '',
    period_start  TEXT    NOT NULL,               -- 填报周期起始日
    period_end    TEXT    NOT NULL DEFAULT '',    -- 填报周期结束日（可能跨周/跨月延伸）
    month         TEXT    NOT NULL,               -- YYYY-MM
    status        TEXT    NOT NULL DEFAULT '草稿',
    snap_name     TEXT    DEFAULT '',
    snap_title    TEXT    DEFAULT '',
    proj_code     TEXT    DEFAULT '',
    proj_name     TEXT    DEFAULT '',
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_user_date ON entries (user_id, work_date);

CREATE INDEX IF NOT EXISTS idx_entries_user_period ON entries (user_id, period_start);
CREATE INDEX IF NOT EXISTS idx_entries_month_user  ON entries (month, user_id);
CREATE INDEX IF NOT EXISTS idx_entries_month       ON entries (month);
CREATE INDEX IF NOT EXISTS idx_entries_date        ON entries (work_date);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    action     TEXT,
    detail     TEXT,
    created_at TEXT
);

-- 撤回申请（v1.5.2）：已提交的填报不能自己撤回，必须管理员审批
CREATE TABLE IF NOT EXISTS withdraw_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    period_start TEXT   NOT NULL,
    period_end  TEXT    NOT NULL DEFAULT '',
    reason      TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT '待审批',  -- 待审批 | 已同意 | 已驳回 | 已失效
    created_at  TEXT,
    decided_at  TEXT,
    decided_by  INTEGER,
    decide_note TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wdreq_status ON withdraw_requests(status);
CREATE INDEX IF NOT EXISTS idx_wdreq_user ON withdraw_requests(user_id, period_start);
"""


def connect():
    """每个线程一个连接（ThreadingHTTPServer 是多线程的）"""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        _local.conn = conn
    return conn


@contextmanager
def transaction():
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def rows(sql, args=()):
    cur = connect().execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def one(sql, args=()):
    cur = connect().execute(sql, args)
    r = cur.fetchone()
    return dict(r) if r else None


def scalar(sql, args=(), default=0):
    cur = connect().execute(sql, args)
    r = cur.fetchone()
    return r[0] if r and r[0] is not None else default


def execute(sql, args=()):
    conn = connect()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def init_db():
    """建表 + 首次启动初始化管理员 + 老版本数据自动升级"""
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()

    _migrate(conn)

    from . import auth, datex

    if not one('SELECT id FROM users WHERE role = ? LIMIT 1', ('admin',)):
        exist = one('SELECT id FROM users WHERE username = ?', (config.ADMIN_DEFAULT_USERNAME,))
        if not exist:
            salt = auth.new_salt()
            execute(
                'INSERT INTO users (username, name, job_title, role, password_hash, salt,'
                ' week_quota, active, track_hours, must_change_pwd, created_at, updated_at)'
                ' VALUES (?,?,?,?,?,?,?,1,0,1,?,?)',
                (config.ADMIN_DEFAULT_USERNAME, config.ADMIN_DEFAULT_NAME, '考勤管理员',
                 'admin', auth.hash_password(config.ADMIN_DEFAULT_PASSWORD, salt), salt,
                 config.WEEK_QUOTA_UNITS, datex.now_str(), datex.now_str()),
            )
        else:
            execute("UPDATE users SET role = 'admin' WHERE username = ?",
                    (config.ADMIN_DEFAULT_USERNAME,))
    return True


def _columns(conn, table):
    return [r[1] for r in conn.execute('PRAGMA table_info(%s)' % table).fetchall()]


def _migrate(conn):
    """
    老版本（按自然周统计）升级到新版本（按填报周期）：
    把 week_start 列改名为 period_start，并补上 period_end；然后用新规则重算周期。
    """
    cols = _columns(conn, 'entries')
    changed = False
    if 'week_start' in cols and 'period_start' not in cols:
        conn.execute('ALTER TABLE entries RENAME COLUMN week_start TO period_start')
        changed = True
        cols = _columns(conn, 'entries')
    if 'period_end' not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN period_end TEXT NOT NULL DEFAULT ''")
        changed = True
        cols = _columns(conn, 'entries')
    # v1.3：半天格 → 明细条目
    if 'hours' not in cols:
        conn.execute('ALTER TABLE entries ADD COLUMN hours REAL NOT NULL DEFAULT 0')
        changed = True
        cols = _columns(conn, 'entries')
    if 'seq' not in cols:
        conn.execute('ALTER TABLE entries ADD COLUMN seq INTEGER NOT NULL DEFAULT 0')
        changed = True
        cols = _columns(conn, 'entries')
    if 'work_kind' not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN work_kind TEXT NOT NULL DEFAULT '正常'")
        changed = True
        cols = _columns(conn, 'entries')
    # v1.5：人员性质（研发人员 / 辅助人员）
    ucols = _columns(conn, 'users')
    if 'person_type' not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN person_type TEXT NOT NULL DEFAULT '研发人员'")
        changed = True
    # 老数据：把 rd/nrd 补进 hours
    conn.execute('UPDATE entries SET hours = rd_hours + nrd_hours WHERE hours = 0 ')
    if changed:
        try:
            from . import datex
            rows = conn.execute(
                "SELECT id, work_date FROM entries WHERE period_end IS NULL OR period_end = ''"
            ).fetchall()
            for rid, wd in rows:
                d = datex.parse_ymd(wd)
                ps, pe = datex.period_of_date(d)
                conn.execute(
                    'UPDATE entries SET period_start = ?, period_end = ? WHERE id = ?',
                    (ps.isoformat(), pe.isoformat(), rid))
        except Exception:
            pass
    conn.commit()

    # 工资月口径（默认「上月26日~当月25日」）：
    # 口径一变，每条记录所属的月份和填报周期都会变，这里整体重算一遍。
    # 用 settings 记住上次用的口径，只在真的变了才重算。
    try:
        from . import datex
        want = str(datex.cycle_start_day())
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'month_cycle_start_day'").fetchone()
        have = (row[0] if row else '') or ''
        if have != want:
            rows = conn.execute('SELECT id, work_date FROM entries').fetchall()
            for rid, wd in rows:
                d = datex.parse_ymd(wd)
                ps, pe = datex.period_of_date(d)
                conn.execute(
                    'UPDATE entries SET month = ?, period_start = ?, period_end = ?'
                    ' WHERE id = ?',
                    (datex.month_key(d), ps.isoformat(), pe.isoformat(), rid))
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('month_cycle_start_day', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (want,))
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------- settings
def get_setting(key, default=None):
    r = one('SELECT value FROM settings WHERE key = ?', (key,))
    return r['value'] if r else default


def set_setting(key, value):
    execute('INSERT INTO settings (key, value) VALUES (?, ?)'
            ' ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, str(value)))
    return True


def audit(user_id, action, detail=''):
    try:
        from . import datex
        execute('INSERT INTO audit_log (user_id, action, detail, created_at) VALUES (?,?,?,?)',
                (user_id, action, detail, datex.now_str()))
    except Exception:
        pass
