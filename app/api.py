# -*- coding: utf-8 -*-
"""HTTP 接口层：路由分发、会话鉴权、静态资源"""
import json
import mimetypes
import os
import posixpath
import re
import traceback
import urllib.parse
from datetime import date

from . import auth, config, db, datex, notify, report, service
from .errors import ApiError, forbidden, not_found, unauthorized


class FileResponse(object):
    """二进制/文件响应"""

    def __init__(self, data=None, path=None, content_type=None, filename=None):
        self.data = data
        self.path = path
        self.content_type = content_type or 'application/octet-stream'
        self.filename = filename


# ---------------------------------------------------------------- 工具
def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _lan_addresses():
    """本机局域网地址列表（给前端显示"请用这个地址访问"）"""
    import socket
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            if not ip.startswith('127.'):
                out.append(ip)
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith('127.'):
                out.append(ip)
    except Exception:
        pass
    return ['http://%s:%d' % (ip, config.PORT) for ip in out]


# ================================================================ 各个接口
def h_ping(ctx, q, body):
    return {'ok': True, 'name': config.SERVER_NAME, 'version': '1.4.0',
            'time': datex.now_str(), 'lanAddresses': _lan_addresses(),
            'monthCycleStartDay': datex.cycle_start_day(),
            'currentMonth': datex.month_key(date.today())}


def h_login(ctx, q, body):
    username = body.get('username') or body.get('name')
    password = body.get('password')
    user, err = auth.login(username, password)
    if err:
        raise ApiError('LOGIN_FAILED', err, 401)
    token = auth.create_session(user['id'])
    db.audit(user['id'], 'login', username)
    return {'ok': True, 'user': auth.public_user(user), 'token': token,
            'mustChangePwd': bool(user['must_change_pwd'])}


def h_logout(ctx, q, body):
    auth.destroy_session(ctx.get('token'))
    return {'ok': True}


def h_me(ctx, q, body):
    return {'ok': True, 'user': auth.public_user(ctx['user']),
            'lanAddresses': _lan_addresses(),
            'serverTime': datex.now_str()}


def h_change_password(ctx, q, body):
    old = str(body.get('oldPassword') or '')
    new = str(body.get('newPassword') or '')
    u = ctx['user']
    if not auth.verify_password(old, u['salt'], u['password_hash']):
        raise ApiError('WRONG_PASSWORD', '原密码不正确', 400)
    if len(new) < 6:
        raise ApiError('INVALID_INPUT', '新密码至少 6 位', 400)
    auth.set_password(u['id'], new)
    db.audit(u['id'], 'change_password')
    return {'ok': True, 'message': '密码已修改'}


# ---------------------------------------------------------------- 填报
def h_get_period(ctx, q, body):
    return {'ok': True,
            'data': service.get_period(ctx['user'], q.get('periodStart', [None])[0])}


def h_save_period(ctx, q, body):
    return {'ok': True, 'data': service.save_period(ctx['user'], body)}


def h_submit_period(ctx, q, body):
    return {'ok': True, 'data': service.submit_period(ctx['user'], body)}


def h_withdraw_period(ctx, q, body):
    return {'ok': True, 'data': service.withdraw_period(ctx['user'], body)}


# ---------------------------------------------------------------- 撤回审批（管理员）
def h_wdreq_list(ctx, q, body):
    only_pending = q.get('all', ['0'])[0] not in ('1', 'true', 'yes')
    rows = service.withdraw_requests_list(only_pending=only_pending,
                                          status=q.get('status', [None])[0])
    return {'ok': True, 'data': {'requests': rows, 'pending': len(rows)}}


def h_wdreq_decide(ctx, q, body):
    return {'ok': True, 'data': service.decide_withdraw(ctx['user'], body)}


def h_copy_prev(ctx, q, body):
    return {'ok': True, 'data': service.copy_prev_period(ctx['user'], body)}


def h_my_status(ctx, q, body):
    return {'ok': True, 'data': service.my_status(ctx['user'], q.get('month', [None])[0])}


def h_projects(ctx, q, body):
    return {'ok': True, 'projects': service.projects_list(active_only=True)}


# ---------------------------------------------------------------- 年度台账
def h_year_ledger(ctx, q, body):
    year = q.get('year', [None])[0] or datex.today_str()[:4]
    uid = q.get('userId', [None])[0]
    return {'ok': True, 'data': service.year_ledger(year, uid, ctx['user'])}


def h_year_export(ctx, q, body):
    year = q.get('year', [None])[0] or datex.today_str()[:4]
    uid = q.get('userId', [None])[0]
    ledger = service.year_ledger(year, uid, ctx['user'])
    path, fname, _ = report.generate_year(ledger)
    db.audit(ctx['user']['id'], 'export_year', '%s %s' % (year, fname))
    return FileResponse(
        path=path,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        filename=fname)


# ---------------------------------------------------------------- 管理员：项目
def h_admin_projects(ctx, q, body):
    return {'ok': True, 'projects': service.projects_list(active_only=False)}


def h_admin_project_save(ctx, q, body):
    if body.get('id'):
        return {'ok': True, 'data': service.update_project(body)}
    return {'ok': True, 'data': service.create_project(body)}


def h_admin_project_toggle(ctx, q, body):
    return {'ok': True, 'data': service.toggle_project(body)}


def h_admin_project_import(ctx, q, body):
    if body.get('text'):
        rows = service.parse_project_text(body['text'])
    else:
        rows = body.get('rows') or []
    return {'ok': True, 'data': service.import_projects(rows)}


def h_admin_project_import_file(ctx, q, body):
    raw = ctx.get('rawBody') or b''
    filename = (q.get('filename', [''])[0] or '').lower()
    if not raw:
        raise ApiError('INVALID_INPUT', '没有收到文件内容', 400)
    if filename.endswith('.csv') or filename.endswith('.txt'):
        rows = service.parse_project_csv(raw)
    else:
        rows = service.parse_project_xlsx(raw)
    return {'ok': True, 'data': service.import_projects(rows)}


# ---------------------------------------------------------------- 管理员：人员
def h_admin_users(ctx, q, body):
    return {'ok': True, 'users': service.users_list()}


def h_admin_user_save(ctx, q, body):
    return {'ok': True, 'data': service.save_user(body)}


def h_admin_user_reset(ctx, q, body):
    return {'ok': True, 'data': service.reset_user_password(body)}


def h_admin_user_import(ctx, q, body):
    rows = body.get('rows') or []
    if body.get('text'):
        rows = _parse_user_text(body['text'])
    return {'ok': True, 'data': service.import_users(rows)}


def _parse_user_text(text):
    """每行：账号 [Tab/逗号] 姓名 [岗位] [部门] [每周应填半天]"""
    rows = []
    for line in str(text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line:
            continue
        cols = [c.strip() for c in re.split(r'\t|,|，|;|；|\s{2,}', line) if c.strip()]
        if not cols:
            continue
        if re.search(r'账号|姓名|岗位|部门|account|name', ' '.join(cols), re.I) and len(cols) <= 5 \
                and not re.search(r'[\u4e00-\u9fa5]{2,}', cols[0]):
            continue
        rows.append({
            'username': cols[0],
            'name': cols[1] if len(cols) > 1 else cols[0],
            'jobTitle': cols[2] if len(cols) > 2 else '',
            'dept': cols[3] if len(cols) > 3 else '',
            'weekQuota': cols[4] if len(cols) > 4 else config.WEEK_QUOTA_UNITS,
        })
    return rows


# ---------------------------------------------------------------- 管理员：监控
def h_admin_period_status(ctx, q, body):
    return {'ok': True,
            'data': service.period_status(q.get('periodStart', [None])[0]
                                          or q.get('weekStart', [None])[0])}


def h_admin_missing(ctx, q, body):
    return {'ok': True,
            'data': service.missing_members(q.get('periodStart', [None])[0]
                                            or q.get('weekStart', [None])[0])}


def h_admin_remind(ctx, q, body):
    value = body.get('periodStart') or body.get('weekStart')
    data = service.missing_members(value)
    if data['count'] == 0:
        return {'ok': True, 'data': {'sent': False, 'message': '本周期所有人都已提交，无需提醒'}}
    app_url = (body.get('appUrl') or '').strip()
    if not app_url:
        urls = _lan_addresses()
        app_url = urls[0] if urls else ''
    text = notify.build_remind_text(data, app_url)
    ok, msg = notify.send_text(text)
    db.audit(ctx['user']['id'], 'remind',
             'period=%s count=%d ok=%s' % (data['periodStart'], data['count'], ok))
    return {'ok': ok, 'data': {'sent': ok, 'message': msg, 'count': data['count'],
                               'preview': text}}


# ---------------------------------------------------------------- 管理员：原始记录导出
def h_admin_export_raw(ctx, q, body):
    """导出每周每人的原始记录，用于留底保存"""
    params = {
        'month': q.get('month', [None])[0],
        'period': q.get('period', [None])[0],
        'from': q.get('from', [None])[0],
        'to': q.get('to', [None])[0],
        'userId': q.get('userId', [None])[0],
    }
    fmt = (q.get('format', ['xlsx'])[0] or 'xlsx').lower()
    if fmt == 'json':
        data = service.export_rows(params)
        rows = data['rows'][:200]
        return {'ok': True, 'data': {
            'count': data['count'], 'rows': rows,
            'byPerson': data['byPerson'], 'byPeriod': data['byPeriod'],
            'truncated': data['count'] > 200,
            'filter': data['filter'],
        }}
    if fmt == 'csv':
        path, fname, data = report.generate_raw_csv(params)
        ctype = 'text/csv; charset=utf-8'
    else:
        path, fname, data = report.generate_raw(params)
        ctype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    db.audit(ctx['user']['id'], 'export_raw', '%s -> %s (%d 条)'
             % (json.dumps(params, ensure_ascii=False), fname, data['count']))
    return FileResponse(path=path, content_type=ctype, filename=fname)


# ---------------------------------------------------------------- 管理员：报表
def _exclude_ids(raw):
    """把 '2,5' 或 [2,5] 或 ['2','5'] 统一成 [2,5]"""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(',')
    out = []
    for x in raw:
        try:
            v = int(str(x).strip())
            if v > 0:
                out.append(v)
        except (TypeError, ValueError):
            pass
    return out


def _member_options(month):
    """月度统计里可供勾选的人员（当月有填报的会带上工时，方便识别误填）"""
    rows = db.rows(
        "SELECT u.id, u.name, u.job_title, u.dept,"
        " COALESCE(SUM(e.rd_hours),0) AS rd, COALESCE(SUM(e.nrd_hours),0) AS nrd,"
        " COUNT(e.id) AS units"
        ' FROM users u LEFT JOIN entries e ON e.user_id = u.id AND e.month = ?'
        ' WHERE u.active = 1 AND u.track_hours = 1 GROUP BY u.id ORDER BY u.name',
        (month,))
    return [{'id': r['id'], 'name': r['name'], 'jobTitle': r['job_title'] or '',
             'dept': r['dept'] or '', 'rd': r['rd'], 'nrd': r['nrd'],
             'units': r['units']} for r in rows]


def h_admin_preview(ctx, q, body):
    month = datex.normalize_month(q.get('month', [None])[0])
    excl = _exclude_ids(q.get('excludeUserIds', [None])[0])
    data = service.month_summary(month, excl)
    return {'ok': True, 'data': {
        'month': data['month'], 'monthLabel': data['monthLabel'],
        'stats': data['stats'], 'breakdown': data['breakdown'],
        'perPerson': data['perPerson'],
        'perProject': data['perProject'],
        'detailSample': data['detail'][:20],
        'periods': report.month_period_rows(month, excl),
        'months': _available_months(),
        'members': _member_options(month),
        'excluded': excl,
    }}


def _available_months():
    rs = db.rows('SELECT DISTINCT month FROM entries ORDER BY month DESC')
    months = [r['month'] for r in rs if r['month']]
    cur = datex.normalize_month(None)
    if cur not in months:
        months.insert(0, cur)
    return months


def h_admin_report(ctx, q, body):
    month = datex.normalize_month(body.get('month'))
    excl = _exclude_ids(body.get('excludeUserIds'))
    path, fname, data = report.generate(month, None, excl)
    db.audit(ctx['user']['id'], 'generate_report',
             '%s -> %s (排除 %d 人)' % (month, fname, len(excl)))
    url = '/api/admin/report/download?month=%s' % month
    if excl:
        url += '&excludeUserIds=' + ','.join(str(x) for x in excl)
    return {'ok': True, 'data': {
        'month': month, 'monthLabel': data['monthLabel'], 'fileName': fname,
        'downloadUrl': url, 'excluded': excl,
        'stats': data['stats'], 'fileSize': os.path.getsize(path),
    }}


def h_admin_report_download(ctx, q, body):
    month = datex.normalize_month(q.get('month', [None])[0])
    excl = _exclude_ids(q.get('excludeUserIds', [None])[0])
    fname = '%s研发工时统计表.xlsx' % datex.month_info(month)['label']
    path = os.path.join(config.OUTPUT_DIR, fname)
    if excl or not os.path.exists(path):
        path, fname, _ = report.generate(month, None, excl)
    return FileResponse(
        path=path,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        filename=fname)


def h_admin_backup(ctx, q, body):
    """下载数据库备份"""
    import shutil
    import sqlite3
    name = 'ts_backup_%s.db' % datex.now_str().replace(':', '').replace(' ', '_')
    dst = os.path.join(config.BACKUP_DIR, name)
    try:
        src = db.connect()
        out = sqlite3.connect(dst)
        try:
            src.backup(out)
        finally:
            out.close()
    except Exception:
        shutil.copyfile(config.DB_PATH, dst)
    db.audit(ctx['user']['id'], 'backup', name)
    return FileResponse(path=dst, content_type='application/octet-stream', filename=name)


# ---------------------------------------------------------------- 管理员：设置
def h_admin_settings(ctx, q, body):
    return {'ok': True, 'data': {
        'feishuWebhook': db.get_setting('feishu_webhook') or config.FEISHU_WEBHOOK or '',
        'remindEnabled': (db.get_setting('remind_enabled') or str(config.REMIND_ENABLED)) == 'True',
        'remindWeekday': int(db.get_setting('remind_weekday') or config.REMIND_WEEKDAY),
        'remindHour': int(db.get_setting('remind_hour') or config.REMIND_HOUR),
        'serverInfo': {
            'name': config.SERVER_NAME,
            'port': config.PORT,
            'halfDayHours': config.HALF_DAY_HOURS,
            'weekQuota': config.WEEK_QUOTA_UNITS,
            'enforceFullWeek': config.ENFORCE_FULL_WEEK,
            'minContentLen': config.MIN_CONTENT_LEN,
            'dbPath': config.DB_PATH,
            'outputDir': config.OUTPUT_DIR,
            'lanAddresses': _lan_addresses(),
        },
    }}


def h_admin_settings_save(ctx, q, body):
    if 'feishuWebhook' in body:
        db.set_setting('feishu_webhook', str(body.get('feishuWebhook') or '').strip())
    if 'remindEnabled' in body:
        db.set_setting('remind_enabled', str(bool(body.get('remindEnabled'))))
    if 'remindWeekday' in body:
        db.set_setting('remind_weekday', int(body.get('remindWeekday') or 4))
    if 'remindHour' in body:
        db.set_setting('remind_hour', int(body.get('remindHour') or 17))
    db.audit(ctx['user']['id'], 'save_settings')
    return {'ok': True, 'message': '设置已保存'}


def h_admin_test_webhook(ctx, q, body):
    ok, msg = notify.send_text('【工时统计系统】飞书群提醒测试消息，收到说明配置成功。')
    return {'ok': ok, 'data': {'message': msg}}


# ================================================================ 路由表
ROUTES = [
    ('GET', '/api/ping', h_ping, False),
    ('POST', '/api/login', h_login, False),
    ('POST', '/api/logout', h_logout, False),
    ('GET', '/api/me', h_me, False),
    ('POST', '/api/password', h_change_password, False),

    ('GET', '/api/period', h_get_period, False),
    ('POST', '/api/period/save', h_save_period, False),
    ('POST', '/api/period/submit', h_submit_period, False),
    ('POST', '/api/period/withdraw', h_withdraw_period, False),
    ('GET', '/api/admin/withdraw-requests', h_wdreq_list, True),
    ('POST', '/api/admin/withdraw-decide', h_wdreq_decide, True),
    ('POST', '/api/period/copy-prev', h_copy_prev, False),
    ('GET', '/api/my-status', h_my_status, False),
    ('GET', '/api/projects', h_projects, False),

    ('GET', '/api/year', h_year_ledger, False),
    ('GET', '/api/year/export', h_year_export, False),

    ('GET', '/api/admin/projects', h_admin_projects, True),
    ('POST', '/api/admin/project/save', h_admin_project_save, True),
    ('POST', '/api/admin/project/toggle', h_admin_project_toggle, True),
    ('POST', '/api/admin/project/import', h_admin_project_import, True),
    ('POST', '/api/admin/project/import-file', h_admin_project_import_file, True),

    ('GET', '/api/admin/users', h_admin_users, True),
    ('POST', '/api/admin/user/save', h_admin_user_save, True),
    ('POST', '/api/admin/user/reset', h_admin_user_reset, True),
    ('POST', '/api/admin/user/import', h_admin_user_import, True),

    ('GET', '/api/admin/period-status', h_admin_period_status, True),
    ('GET', '/api/admin/week-status', h_admin_period_status, True),
    ('GET', '/api/admin/missing', h_admin_missing, True),
    ('POST', '/api/admin/remind', h_admin_remind, True),

    ('GET', '/api/admin/preview', h_admin_preview, True),
    ('POST', '/api/admin/report', h_admin_report, True),
    ('GET', '/api/admin/report/download', h_admin_report_download, True),
    ('GET', '/api/admin/export/raw', h_admin_export_raw, True),
    ('GET', '/api/admin/backup', h_admin_backup, True),
    ('GET', '/api/admin/settings', h_admin_settings, True),
    ('POST', '/api/admin/settings', h_admin_settings_save, True),
    ('POST', '/api/admin/test-webhook', h_admin_test_webhook, True),
]

_ROUTE_MAP = {(m, p): (fn, adm) for (m, p, fn, adm) in ROUTES}

PUBLIC_PATHS = {'/api/ping', '/api/login'}


def is_api(path):
    return path.startswith('/api/')


def dispatch(method, path, query, body, ctx):
    """
    处理 API 请求，返回 (status, payload)
    payload: dict（转 JSON）或 FileResponse
    """
    key = (method, path)
    hit = _ROUTE_MAP.get(key)
    if not hit:
        for (m, p), v in _ROUTE_MAP.items():
            if m == method and p == path:
                hit = v
                break
    if not hit:
        return 404, {'ok': False, 'code': 'NOT_FOUND', 'message': '接口不存在：%s' % path}

    fn, admin_only = hit

    if path not in PUBLIC_PATHS and not ctx.get('user'):
        return 401, {'ok': False, 'code': 'UNAUTHORIZED', 'message': '请先登录'}

    if admin_only:
        u = ctx.get('user')
        if not u or u['role'] != 'admin':
            return 403, {'ok': False, 'code': 'FORBIDDEN', 'message': '该操作仅管理员可用'}

    try:
        out = fn(ctx, query, body)
        if isinstance(out, FileResponse):
            return 200, out
        status = 200
        if isinstance(out, dict) and out.get('ok') is False:
            status = 200
        return status, out
    except ApiError as e:
        return e.status, e.to_dict()
    except Exception as e:
        traceback.print_exc()
        return 500, {'ok': False, 'code': 'INTERNAL_ERROR',
                     'message': '服务器内部错误：%s' % e}


# ---------------------------------------------------------------- 静态文件
_STATIC_ALIAS = {
    '/': 'index.html',
    '/index.html': 'index.html',
}


def resolve_static(path):
    """把 URL 映射到 static 目录下的文件，防目录穿越"""
    if path in _STATIC_ALIAS:
        rel = _STATIC_ALIAS[path]
    else:
        rel = path.lstrip('/')
    rel = posixpath.normpath(rel)
    if rel.startswith('..') or rel.startswith('/'):
        return None
    full = os.path.join(config.STATIC_DIR, rel.replace('/', os.sep))
    if not os.path.abspath(full).startswith(os.path.abspath(config.STATIC_DIR)):
        return None
    return full if os.path.isfile(full) else None


def content_type_of(path):
    ext = os.path.splitext(path)[1].lower()
    mapping = {'.html': 'text/html; charset=utf-8',
               '.css': 'text/css; charset=utf-8',
               '.js': 'application/javascript; charset=utf-8',
               '.json': 'application/json; charset=utf-8',
               '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
               '.ico': 'image/x-icon', '.woff2': 'font/woff2'}
    return mapping.get(ext) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
