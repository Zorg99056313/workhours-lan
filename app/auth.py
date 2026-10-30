# -*- coding: utf-8 -*-
"""口令哈希与会话管理"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from . import config, db, datex


# ---------------------------------------------------------------- 口令
def new_salt():
    return secrets.token_hex(16)


def hash_password(password, salt):
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                             salt.encode('utf-8'), config.PBKDF2_ITERATIONS)
    return dk.hex()


def verify_password(password, salt, expected_hash):
    calc = hash_password(password, salt)
    return hmac.compare_digest(calc, expected_hash)


def set_password(user_id, password):
    salt = new_salt()
    db.execute('UPDATE users SET password_hash = ?, salt = ?, must_change_pwd = 0,'
               ' updated_at = ? WHERE id = ?',
               (hash_password(password, salt), salt, datex.now_str(), user_id))
    return True


# ---------------------------------------------------------------- 会话
def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    db.execute('INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)',
               (token, user_id, now.strftime('%Y-%m-%d %H:%M:%S'),
                (now + timedelta(days=config.SESSION_TTL_DAYS)).strftime('%Y-%m-%d %H:%M:%S')))
    return token


def get_session_user(token):
    if not token:
        return None
    r = db.one('SELECT s.user_id, s.expires_at FROM sessions s WHERE s.token = ?', (token,))
    if not r:
        return None
    if datetime.strptime(r['expires_at'], '%Y-%m-%d %H:%M:%S') < datetime.now():
        db.execute('DELETE FROM sessions WHERE token = ?', (token,))
        return None
    return db.one('SELECT * FROM users WHERE id = ? AND active = 1', (r['user_id'],))


def destroy_session(token):
    if token:
        db.execute('DELETE FROM sessions WHERE token = ?', (token,))
    return True


def cleanup_sessions():
    db.execute('DELETE FROM sessions WHERE expires_at < ?',
               (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))


def login(username, password):
    u = db.one('SELECT * FROM users WHERE username = ?', (str(username or '').strip(),))
    if not u:
        return None, '账号不存在'
    if not u['active']:
        return None, '该账号已停用，请联系管理员'
    if not verify_password(str(password or ''), u['salt'], u['password_hash']):
        return None, '密码不正确'
    return u, None


def _row_get(row, key, default=''):
    """sqlite3.Row 没有 .get()，这里做个安全取值（列不存在时返回默认值）"""
    try:
        if isinstance(row, dict):
            v = row.get(key)
        else:
            v = row[key] if key in row.keys() else None
        return default if v in (None, '') else v
    except (KeyError, IndexError):
        return default


def public_user(u):
    """给前端的安全字段（去掉 hash/salt）"""
    if not u:
        return None
    return {
        'id': u['id'],
        'username': u['username'],
        'name': u['name'],
        'jobTitle': u['job_title'] or '',
        'dept': u['dept'] or '',
        'role': u['role'],
        'isAdmin': u['role'] == 'admin',
        'personType': _row_get(u, 'person_type', '研发人员'),
        'weekQuota': u['week_quota'],
        'mustChangePwd': bool(u['must_change_pwd']),
    }
