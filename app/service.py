# -*- coding: utf-8 -*-
"""业务逻辑层：填报周期、工时记录、项目库、人员、年度台账、原始导出、统计口径"""
import io
import re
from datetime import date

from . import config, datex, db, rules
from .errors import ApiError, bad_request, forbidden, not_found, validate_failed

HALF = config.HALF_DAY_HOURS
EMPTY = config.EMPTY_MARK


# ================================================================ 项目库
def project_map(active_only=False):
    sql = 'SELECT * FROM projects'
    if active_only:
        sql += ' WHERE active = 1'
    out = {}
    for r in db.rows(sql + ' ORDER BY sort, code'):
        out[r['id']] = r
    return out


def projects_list(active_only=True, keyword=None):
    sql = 'SELECT * FROM projects'
    cond, args = [], []
    if active_only:
        cond.append('active = 1')
    if cond:
        sql += ' WHERE ' + ' AND '.join(cond)
    sql += ' ORDER BY sort, code'
    items = db.rows(sql, args)
    if keyword:
        kw = str(keyword).strip().lower()
        items = [p for p in items
                 if kw in (p['code'] or '').lower() or kw in (p['name'] or '').lower()]
    return [{
        'id': p['id'], 'code': p['code'], 'name': p['name'], 'type': p['ptype'],
        'status': p['status'], 'active': bool(p['active']), 'sort': p['sort'],
        'remark': p['remark'] or '',
    } for p in items]


def _all_project_ids():
    return {r['id'] for r in db.rows('SELECT id FROM projects')}


def next_auto_code():
    year = date.today().year
    prefix = 'RD-%d-' % year
    mx = 0
    for r in db.rows('SELECT code FROM projects'):
        m = re.match(r'^%s(\d+)$' % re.escape(prefix), r['code'] or '')
        if m:
            mx = max(mx, int(m.group(1)))
    return '%s%02d' % (prefix, mx + 1)


def create_project(data):
    name = str(data.get('name') or '').strip()
    if not name:
        raise bad_request('请填写项目名称')
    code = str(data.get('code') or '').strip() or next_auto_code()
    if db.one('SELECT id FROM projects WHERE code = ?', (code,)):
        raise bad_request('项目编号 %s 已存在' % code)
    pid = db.execute(
        'INSERT INTO projects (code, name, ptype, status, active, sort, remark, created_at)'
        ' VALUES (?,?,?,?,1,?,?,?)',
        (code, name, _type_of(data.get('type')), '进行中',
         int(data.get('sort') or 0), str(data.get('remark') or ''), datex.now_str()))
    return {'id': pid, 'code': code, 'name': name}


def update_project(data):
    pid = int(data.get('id') or 0)
    if not pid:
        raise bad_request('缺少项目 ID')
    row = db.one('SELECT * FROM projects WHERE id = ?', (pid,))
    if not row:
        raise not_found('项目不存在')
    sets, args = [], []
    if data.get('code') is not None:
        code = str(data['code']).strip()
        if not code:
            raise bad_request('项目编号不能为空')
        dup = db.one('SELECT id FROM projects WHERE code = ? AND id <> ?', (code, pid))
        if dup:
            raise bad_request('项目编号 %s 已被占用' % code)
        sets.append('code = ?'); args.append(code)
    if data.get('name') is not None:
        sets.append('name = ?'); args.append(str(data['name']).strip())
    if data.get('type') is not None:
        sets.append('ptype = ?'); args.append(_type_of(data['type']))
    if data.get('status') is not None:
        sets.append('status = ?')
        args.append('已结项' if re.search(r'结项|完成|done|closed', str(data['status']), re.I) else '进行中')
    if data.get('active') is not None:
        sets.append('active = ?'); args.append(1 if data['active'] else 0)
    if data.get('sort') is not None:
        sets.append('sort = ?'); args.append(int(data['sort'] or 0))
    if data.get('remark') is not None:
        sets.append('remark = ?'); args.append(str(data['remark']))
    if not sets:
        raise bad_request('没有要修改的内容')
    args.append(pid)
    db.execute('UPDATE projects SET %s WHERE id = ?' % ', '.join(sets), tuple(args))
    return {'id': pid}


def toggle_project(data):
    pid = int(data.get('id') or 0)
    active = bool(data.get('active'))
    if not pid:
        raise bad_request('缺少项目 ID')
    db.execute('UPDATE projects SET active = ?, status = ? WHERE id = ?',
               (1 if active else 0, '进行中' if active else '已结项', pid))
    return {'id': pid, 'active': active}


def _type_of(v):
    return '非研发' if re.search(r'非研发|nrd|non', str(v or ''), re.I) else '研发'


def parse_project_text(text):
    """解析粘贴文本：每行「编号 [Tab/逗号/空格] 名称 [类型]」，自动跳过表头"""
    out = []
    for line in str(text or '').replace('\r', '').split('\n'):
        line = line.strip()
        if not line:
            continue
        cols = [c.strip() for c in re.split(r'\t|,|，|;|；|\s{2,}', line) if c.strip()]
        if not cols:
            continue
        joined = ' '.join(cols)
        if re.match(r'^(项目)?(编号|编码|code)$', cols[0], re.I):
            continue
        if len(cols) <= 2 and re.search(r'编号|名称|类型|code|name|type', joined, re.I) \
                and not re.search(r'[\u4e00-\u9fa5]{3,}', cols[-1]):
            continue
        if len(cols) == 1:
            out.append({'code': '', 'name': cols[0], 'type': ''})
        elif re.match(r'^[A-Za-z0-9\-_.]{2,30}$', cols[0]):
            out.append({'code': cols[0], 'name': cols[1],
                        'type': cols[2] if len(cols) > 2 else ''})
        else:
            out.append({'code': '', 'name': cols[0],
                        'type': cols[1] if len(cols) > 1 else ''})
    return out


def parse_project_xlsx(data):
    """从上传的 xlsx 读取项目行（第 1 列=编号，第 2 列=名称，第 3 列=类型）"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb.worksheets[0]
    out = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if row is None:
            continue
        cells = ['' if v is None else str(v).strip() for v in row[:4]]
        if not any(cells):
            continue
        a, b, c = (cells + ['', '', ''])[:3]
        if i == 0 and re.search(r'编号|名称|类型|code|name|type', ' '.join(cells), re.I):
            continue
        out.append({'code': a, 'name': b or a, 'type': c})
    wb.close()
    return out


def parse_project_csv(data):
    text = None
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        raise bad_request('CSV 文件编码无法识别，请另存为 UTF-8 或直接粘贴')
    return parse_project_text(text.replace(',', '\t') if '\t' not in text else text)


def import_projects(rows):
    """批量导入/更新项目，返回统计"""
    items = []
    for r in (rows or []):
        name = str(r.get('name') or '').strip()
        code = str(r.get('code') or '').strip()
        if not name and not code:
            continue
        items.append({'code': code, 'name': name or code, 'type': _type_of(r.get('type'))})
    if not items:
        raise bad_request('没有解析到有效项目，请确认每行至少包含「项目名称」')

    existing = db.rows('SELECT * FROM projects')
    by_code = {p['code']: p for p in existing}
    by_name = {p['name']: p for p in existing}

    created = updated = skipped = 0
    errors = []
    for it in items:
        target = by_code.get(it['code']) if it['code'] else None
        if not target:
            target = by_name.get(it['name'])
        if target:
            sets, args = [], []
            if it['name'] and it['name'] != target['name']:
                sets.append('name = ?'); args.append(it['name'])
            if it['type'] != target['ptype']:
                sets.append('ptype = ?'); args.append(it['type'])
            if not sets:
                skipped += 1
                continue
            args.append(target['id'])
            db.execute('UPDATE projects SET %s WHERE id = ?' % ', '.join(sets), tuple(args))
            updated += 1
            continue
        code = it['code'] or next_auto_code()
        if code in by_code:
            errors.append({'code': code, 'name': it['name'], 'message': '项目编号已存在'})
            continue
        pid = db.execute(
            'INSERT INTO projects (code, name, ptype, status, active, sort, remark, created_at)'
            ' VALUES (?,?,?,?,1,0,"",?)',
            (code, it['name'], it['type'], '进行中', datex.now_str()))
        newrow = {'id': pid, 'code': code, 'name': it['name'], 'ptype': it['type']}
        by_code[code] = newrow
        by_name[it['name']] = newrow
        created += 1

    return {'created': created, 'updated': updated, 'skipped': skipped,
            'errors': errors, 'projects': projects_list(active_only=False)}


# ================================================================ 填报周期（明细条目模型）
def _resolve_period(value):
    """把前端传来的任意日期（周期起始日/周中某天）落到真正的周期上"""
    d = datex.parse_ymd(value)
    ps, pe = datex.period_of_date(d)
    return ps, pe


def _fill_state(user, ps, pe):
    """
    这个周期现在能不能填？返回 (editable, reason)

    规则（可在 app/config.py 里改）：
      · FILL_REQUIRE_PERIOD_ENDED = True → 周期过完（结束日 < 今天）才能填；
      · ADMIN_CAN_FILL_ANY_PERIOD = True → 管理员可破例（补录/纠错）；
      · FILL_MAX_BACK_PERIODS > 0 → 只能回溯 N 期，更早的锁定。
    """
    today = date.today()
    if pe < today:
        back = int(getattr(config, 'FILL_MAX_BACK_PERIODS', 0) or 0)
        if back > 0:
            # 从「该填的一期」往回数，超过 back 期就锁（数准，不做截断）
            cur_ps, cur_pe = datex.fillable_period(today)
            n, ps2, pe2 = 0, cur_ps, cur_pe
            while pe2 > pe and n < 1000:
                ps2, pe2 = datex.prev_period(ps2)
                n += 1
            if pe2 == pe and n > back \
                    and not (getattr(config, 'ADMIN_CAN_FILL_ANY_PERIOD', True)
                             and (user or {}).get('role') == 'admin'):
                return False, ('这一期已经是 %d 期前的了，超过可回溯的 %d 期上限，已锁定。'
                               '需要更正请联系管理员。' % (n, back))
        return True, ''
    if not getattr(config, 'FILL_REQUIRE_PERIOD_ENDED', True):
        return True, ''
    if getattr(config, 'ADMIN_CAN_FILL_ANY_PERIOD', True) \
            and (user or {}).get('role') == 'admin':
        return True, ''

    start = datex.fillable_from(pe).isoformat()
    if ps <= today <= pe:
        reason = ('本期还没结束（%s ~ %s），%s 起才能填。'
                  '按实际做完的工作填写更真实，也能避免提前把还没上的班写进去。'
                  % (ps.isoformat(), pe.isoformat(), start))
    else:
        reason = ('本期还没开始（%s ~ %s），要到 %s 之后才能填。'
                  % (ps.isoformat(), pe.isoformat(), start))
    return False, reason


def _ensure_fillable(user, ps, pe):
    """不能填就抛出可读的业务异常"""
    ok, reason = _fill_state(user, ps, pe)
    if not ok:
        raise ApiError('PERIOD_LOCKED', reason, 422)


def _entry_to_item(e):
    """DB 行 -> 前端明细条目"""
    return {
        'id': e['id'],
        'date': e['work_date'],
        'seq': e.get('seq') or 0,
        'work_type': e['work_type'],
        'hours': float(e.get('hours') or (e.get('rd_hours') or 0) + (e.get('nrd_hours') or 0)),
        'project_id': e['project_id'] or '',
        'project_code': e.get('proj_code') or '',
        'project_name': e.get('proj_name') or '',
        'content': e['content'] or '',
        'status': e['status'],
    }


def load_period_entries(user_id, p_start):
    rs = db.rows(
        'SELECT * FROM entries WHERE user_id = ? AND period_start = ?'
        ' ORDER BY work_date, seq, id',
        (user_id, p_start.isoformat()))
    return [_entry_to_item(r) for r in rs]


def _blank_item(date_str, work_type='', kind='正常', hours='', content=''):
    return {'id': None, 'date': date_str, 'seq': 0, 'work_type': work_type,
            'kind': kind, 'hours': hours, 'project_id': '', 'project_code': '',
            'project_name': '', 'content': content, 'status': ''}


def _person_type(user):
    """取人员性质，非法值一律按研发人员处理"""
    t = str((user or {}).get('person_type') or '').strip()
    return t if t in config.PERSON_TYPES else config.PERSON_TYPE_RD


def _is_aux(user):
    return (getattr(config, 'AUX_AUTO_FILL', True)
            and _person_type(user) == config.PERSON_TYPE_AUX)


def _auto_leave_text(d):
    """自动预填的休假写什么：周末就写「周末休息」，调休上班日/节假日另有说法"""
    s = d.isoformat()
    if s in set(config.EXTRA_WORKDAYS or []):
        return '调休上班'
    if s in set(config.HOLIDAYS or []):
        return '法定节假日休息'
    if d.weekday() >= 5:
        return '周末休息'
    return '休息'


def get_period(user, value=None):
    """
    读取某人某个填报周期的明细。
    周期可能 >7 天；每天返回该日下的若干条明细。
    周末/法定节假日若还没填，默认给一条空白「休假」条目（可改成加班/研发），
    但**未来的日期不再预填**——那还没发生，不该先写成休假。
    不指定周期时，落到「最近一个已经过完的周期」（下周填本周）。
    """
    if value:
        ps, pe = _resolve_period(value)
    else:
        ps, pe = datex.fillable_period()
    info = datex.period_info(ps, pe, user['week_quota'])
    editable, lock_reason = _fill_state(user, ps, pe)
    ents = load_period_entries(user['id'], ps)

    by_day = {}
    for e in ents:
        by_day.setdefault(e['date'], []).append(e)

    today = date.today()
    is_aux = _is_aux(user)
    days = []
    for d in info['days']:
        ds = d.isoformat()
        items = by_day.get(ds)
        workday = datex.is_workday(d)
        if items is None:
            if workday and is_aux:
                # 辅助人员：工作日默认「非研发 8 小时 + 部门行政管理事务」，可随意改
                items = [_blank_item(ds, work_type=config.AUX_DEFAULT_TYPE, kind='正常',
                                     hours=config.AUX_DEFAULT_HOURS,
                                     content=config.AUX_DEFAULT_CONTENT)]
            elif workday:
                items = [_blank_item(ds)]
            elif config.AUTO_LEAVE_NON_WORKDAY and d <= today:
                # 休息日预填「休假」时必须带上内容——校验要求休假写清情况，
                # 否则用户一个字都不改直接提交会被拦（以前就有这个坑）。
                items = [_blank_item(ds, work_type='休假', kind='正常', hours=0,
                                     content=_auto_leave_text(d))]
            else:
                items = [_blank_item(ds)]
        days.append({
            'date': ds,
            'weekday': datex.weekday_cn(d),
            'weekdayShort': datex.weekday_cn(d)[-1],
            'isWeekend': datex.is_weekend(d),
            'isWorkday': workday,
            'isToday': d == today,
            'isFuture': d > today,
            'items': items,
        })

    submitted = bool(ents) and all(e['status'] == '已提交' for e in ents)

    # 下拉项目：启用的 + 本期已引用但已停用的
    active = projects_list(active_only=True)
    used = {e['project_id'] for e in ents if e['project_id']}
    have = {p['id'] for p in active}
    for pid in used - have:
        r = db.one('SELECT * FROM projects WHERE id = ?', (pid,))
        if r:
            active.append({'id': r['id'], 'code': r['code'], 'name': r['name'],
                           'type': r['ptype'], 'status': r['status'],
                           'active': False, 'sort': r['sort'], 'remark': ''})

    prev_ps, prev_pe = datex.prev_period(ps)
    next_ps, next_pe = datex.next_period(pe)

    # 本期已填工时统计（只算已落库的）
    rd = sum(float(e.get('rd_hours') or 0) for e in ents)
    nrd = sum(float(e.get('nrd_hours') or 0) for e in ents)
    days_filled = len({e['date'] for e in ents})

    return {
        'periodStart': ps.isoformat(),
        'periodEnd': pe.isoformat(),
        'periodLabel': info['label'],
        'periodDays': info['day_count'],
        'periodExtended': info['extended'],
        'monthLabel': info['month_label'],
        'weekNumber': info['iso_week'],
        'workdays': info['workdays'],
        'days': days,
        'projects': active,
        'daysFilled': days_filled,
        'workdaysTotal': info['workdays'],
        'itemCount': len(ents),
        'totalHours': round(rd + nrd, 1),
        'rdHours': round(rd, 1),
        'nrdHours': round(nrd, 1),
        # 参考值：按旧"每天 8 小时"口径算出的应出勤
        'suggestedHours': round(info['workdays'] * config.HALF_DAY_HOURS * 2, 1),
        'submitted': submitted,
        'editable': editable,
        'lockReason': lock_reason,
        'canEdit': _can_edit_period(user, ps, pe, submitted),
        'withdrawPending': _pending_brief(user['id'], ps) if submitted else None,
        'lastWithdrawResult': _last_withdraw_brief(user['id'], ps) if submitted else None,
        'personType': _person_type(user),
        'isAux': _is_aux(user),
        'auxDefault': {
            'hours': config.AUX_DEFAULT_HOURS,
            'workType': config.AUX_DEFAULT_TYPE,
            'content': config.AUX_DEFAULT_CONTENT,
        } if _is_aux(user) else None,
        'fillableFrom': datex.fillable_from(pe).isoformat(),
        'prevPeriodStart': prev_ps.isoformat(),
        'prevPeriodEnd': prev_pe.isoformat(),
        'nextPeriodStart': next_ps.isoformat(),
        'nextPeriodEnd': next_pe.isoformat(),
        'today': date.today().isoformat(),
        'prevPeriodLabel': '%s~%s' % (prev_ps.isoformat()[5:], prev_pe.isoformat()[5:]),
        'nextPeriodLabel': '%s~%s' % (next_ps.isoformat()[5:], next_pe.isoformat()[5:]),
        'rules': {
            'halfDayHours': config.HALF_DAY_HOURS,
            'dayFillTips': [4, 8],
            'minContentLen': config.MIN_CONTENT_LEN,
            'leaveMinContentLen': config.LEAVE_MIN_CONTENT_LEN,
            'maxDailyHours': config.MAX_DAILY_HOURS,
            'autoLeaveNonWorkday': config.AUTO_LEAVE_NON_WORKDAY,
        },
    }


def _build_entry_rows(user, ps, pe, items, status):
    """明细条目 -> DB 行列表（每条一行）"""
    pmap = project_map()
    rows = []
    per_day_seq = {}

    # 先按日期分组，保证 seq 稳定
    for it in items:
        d = datex.parse_ymd(it.get('date'))
        ds = d.isoformat()
        wt = rules.normalize_work_type(it.get('work_type'))
        content = str(it.get('content') or '').strip()
        if not wt:
            continue
        hours = rules.normalize_hours(it.get('hours'), wt)
        if wt != '休假' and hours <= 0:
            continue

        is_rd = (wt == '研发')
        pid = None
        code = name = EMPTY
        if is_rd:
            try:
                pid = int(it.get('project_id'))
            except (TypeError, ValueError):
                pid = None
            p = pmap.get(pid)
            if p:
                code, name = p['code'], p['name']
            else:
                pid = None

        seq = per_day_seq.get(ds, 0)
        per_day_seq[ds] = seq + 1

        rows.append((
            user['id'], ds, seq, wt, rules.normalize_kind(it.get('kind')), pid,
            hours,
            hours if is_rd else 0,
            hours if wt == '非研发' else 0,
            content, ps.isoformat(), pe.isoformat(), datex.month_key(d), status,
            user['name'] or '', user['job_title'] or '', code, name, datex.now_str(),
        ))
    return rows


_INSERT_SQL = (
    'INSERT INTO entries (user_id, work_date, seq, work_type, work_kind, project_id,'
    ' hours, rd_hours, nrd_hours, content, period_start, period_end, month, status,'
    ' snap_name, snap_title, proj_code, proj_name, updated_at)'
    ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')


def save_period(user, data):
    """
    保存整期明细（覆盖式）。
    只校验「不空置 + 内容合规 + 研发挂项目 + 单日不超上限」，
    合计工时只回传给前端提示，不拦截。
    """
    ps, pe = _resolve_period(
        data.get('periodStart') or data.get('weekStart')
        or ((data.get('items') or data.get('cells') or [{}])[0].get('date')))
    _ensure_fillable(user, ps, pe)

    # v1.5.2：已提交的数据不能被本人直接覆盖，
    # 必须先由管理员审批同意撤回（状态变回草稿）才能改。
    if _period_submitted(user['id'], ps) \
            and str((user or {}).get('role') or '') != 'admin':
        raise ApiError(
            'PERIOD_SUBMITTED',
            '本期已经提交，不能直接修改。如需更正，请点「申请撤回」，'
            '管理员审批通过后即可继续编辑。', 422)

    items = data.get('items')
    if items is None:
        items = data.get('cells') or []
    if not isinstance(items, list):
        raise bad_request('没有收到任何填报数据')

    info = datex.period_info(ps, pe, user['week_quota'])
    require_full = data.get('requireFullDays')
    require_full = True if require_full is None else bool(require_full)

    ok, errs, stat = rules.validate_entries(
        items, info['days'], _all_project_ids(), require_full_days=require_full,
        person_type=_person_type(user))
    if not ok:
        raise validate_failed(errs)

    submit = bool(data.get('submit'))
    status = '已提交' if submit else '草稿'
    rows = _build_entry_rows(user, ps, pe, items, status)
    if not rows:
        raise bad_request('没有有效数据可保存')

    with db.transaction() as conn:
        conn.execute('DELETE FROM entries WHERE user_id = ? AND period_start = ?',
                     (user['id'], ps.isoformat()))
        conn.executemany(_INSERT_SQL, rows)

    suggested = info['workdays'] * config.HALF_DAY_HOURS * 2
    diff = round(stat['totalHours'] - suggested, 1)
    warn = None
    if diff > 0:
        warn = '本期合计 %g 小时，比常规出勤 %g 小时多 %g 小时' % (
            stat['totalHours'], suggested, diff)
    elif diff < 0:
        warn = '本期合计 %g 小时，比常规出勤 %g 小时少 %g 小时' % (
            stat['totalHours'], suggested, -diff)

    return {'periodStart': ps.isoformat(), 'periodEnd': pe.isoformat(),
            'saved': len(rows), 'items': len(rows),
            'daysFilled': stat['daysWithEntry'], 'workdays': stat['workdays'],
            'totalHours': stat['totalHours'], 'rdHours': stat['rdHours'],
            'nrdHours': stat['nrdHours'], 'suggestedHours': round(suggested, 1),
            'submitted': submit, 'warning': warn,
            'message': '本期工时已提交' if submit else '已保存草稿'}


def submit_period(user, data):
    ps, pe = _resolve_period(data.get('periodStart') or data.get('weekStart'))
    _ensure_fillable(user, ps, pe)
    ents = load_period_entries(user['id'], ps)
    if not ents:
        raise not_found('本周期还没有填报内容，请先填写')

    info = datex.period_info(ps, pe, user['week_quota'])
    ok, errs, stat = rules.validate_entries(
        ents, info['days'], _all_project_ids(), require_full_days=True,
        person_type=_person_type(user))
    if not ok:
        raise validate_failed(errs, '还有 %d 处需要处理，补齐后才能提交' % len(errs))

    with db.transaction() as conn:
        conn.execute("UPDATE entries SET status = '已提交', updated_at = ?"
                     ' WHERE user_id = ? AND period_start = ?',
                     (datex.now_str(), user['id'], ps.isoformat()))
    return {'periodStart': ps.isoformat(), 'periodEnd': pe.isoformat(),
            'submitted': True, 'items': len(ents),
            'totalHours': stat['totalHours'],
            'message': '本期 %d 条记录（%g 小时）已提交' % (len(ents), stat['totalHours'])}


def _period_submitted(user_id, ps):
    """该周期是否已提交（有任何一条已提交记录即算）"""
    n = db.scalar("SELECT COUNT(*) FROM entries WHERE user_id = ? AND period_start = ?"
                  " AND status = '已提交'", (user_id, ps.isoformat()))
    return n > 0


def _pending_withdrawal(user_id, ps):
    """该周期是否有待审批的撤回申请"""
    return db.one("SELECT * FROM withdraw_requests WHERE user_id = ? AND period_start = ?"
                  " AND status = '待审批' ORDER BY id DESC LIMIT 1",
                  (user_id, ps.isoformat()))


def _pending_brief(user_id, ps):
    w = _pending_withdrawal(user_id, ps)
    if not w:
        return None
    return {'id': w['id'], 'reason': w['reason'], 'createdAt': w['created_at']}


def _last_withdraw_brief(user_id, ps):
    """最近一条已处理（同意/驳回）的申请，用来告诉用户审批结果"""
    w = db.one("SELECT * FROM withdraw_requests WHERE user_id = ? AND period_start = ?"
               " AND status <> '待审批' ORDER BY id DESC LIMIT 1",
               (user_id, ps.isoformat()))
    if not w:
        return None
    return {'status': w['status'], 'note': w['decide_note'] or '',
            'decidedAt': w['decided_at']}


def _can_edit_period(user, ps, pe, submitted):
    """
    这个周期现在能不能改：
      · 时间窗允许（周期已结束）；
      · 未提交 → 可以改；
      · 已提交 → 只有管理员可以（补录纠错），普通人要等撤回审批通过。
    """
    ok, _ = _fill_state(user, ps, pe)
    if not ok:
        return False
    if not submitted:
        return True
    return str((user or {}).get('role') or '') == 'admin'
def request_withdraw(user, data):
    """
    申请撤回已提交的填报（v1.5.2）。
    已提交的数据使用者自己不能改，只能提请管理员审批；审批同意后才变回草稿。
    """
    ps, pe = _resolve_period(data.get('periodStart') or data.get('weekStart'))
    if not _period_submitted(user['id'], ps):
        raise bad_request('本周期还没有提交过，不需要撤回')
    old = _pending_withdrawal(user['id'], ps)
    if old:
        return {'periodStart': ps.isoformat(), 'requestId': old['id'],
                'status': '待审批', 'message': '已经提交过撤回申请，请等管理员处理'}
    reason = str(data.get('reason') or '').strip()
    if len(reason) < 2:
        raise bad_request('请简单写一下撤回原因（至少 2 个字），方便管理员判断')
    now = datex.now_str()
    nid = db.execute(
        'INSERT INTO withdraw_requests (user_id, period_start, period_end, reason,'
        " status, created_at) VALUES (?,?,?,?,'待审批',?)",
        (user['id'], ps.isoformat(), pe.isoformat(), reason[:200], now))
    db.audit(user['id'], 'withdraw_request', '%s：%s' % (ps.isoformat(), reason[:60]))
    return {'periodStart': ps.isoformat(), 'requestId': nid, 'status': '待审批',
            'message': '撤回申请已提交，等管理员审批通过后即可修改'}


def withdraw_period(user, data):
    """
    撤回：管理员可直接撤回（可代他人撤回，传 userId）；普通成员只能「申请撤回」。
    """
    ps, pe = _resolve_period(data.get('periodStart') or data.get('weekStart'))
    if str((user or {}).get('role') or '') != 'admin':
        return request_withdraw(user, data)
    target_id = user['id']
    try:
        req_uid = int(data.get('userId') or 0)
    except (TypeError, ValueError):
        req_uid = 0
    if req_uid and req_uid != user['id']:
        if not db.one('SELECT id FROM users WHERE id = ?', (req_uid,)):
            raise bad_request('指定的用户不存在')
        target_id = req_uid
    with db.transaction() as conn:
        cur = conn.execute("UPDATE entries SET status = '草稿', updated_at = ?"
                           ' WHERE user_id = ? AND period_start = ?',
                           (datex.now_str(), target_id, ps.isoformat()))
        conn.execute("UPDATE withdraw_requests SET status = '已失效', decided_at = ?"
                     " WHERE user_id = ? AND period_start = ? AND status = '待审批'",
                     (datex.now_str(), target_id, ps.isoformat()))
    if cur.rowcount == 0:
        raise not_found('本周期还没有填报内容')
    return {'periodStart': ps.isoformat(), 'submitted': False,
            'userId': target_id,
            'message': '已撤回，可继续修改'}


# ---------------------------------------------------------------- 撤回审批（管理员）
def withdraw_requests_list(status=None, only_pending=True):
    """管理员看撤回申请列表"""
    sql = ('SELECT r.*, u.name AS u_name, u.username AS u_account,'
           ' u.job_title AS u_title, u.dept AS u_dept'
           ' FROM withdraw_requests r JOIN users u ON u.id = r.user_id')
    args = []
    if only_pending:
        sql += " WHERE r.status = '待审批'"
    elif status:
        sql += ' WHERE r.status = ?'
        args.append(status)
    sql += ' ORDER BY r.id DESC'
    out = []
    for r in db.rows(sql, tuple(args)):
        out.append({
            'id': r['id'], 'userId': r['user_id'], 'name': r['u_name'],
            'account': r['u_account'], 'jobTitle': r['u_title'] or '',
            'dept': r['u_dept'] or '',
            'periodStart': r['period_start'], 'periodEnd': r['period_end'],
            'reason': r['reason'], 'status': r['status'],
            'createdAt': r['created_at'], 'decidedAt': r['decided_at'],
            'decideNote': r['decide_note'] or '',
        })
    return out


def decide_withdraw(admin_user, data):
    """
    审批撤回申请。
    approve=True → 该周期记录变回草稿，本人可继续修改；
    approve=False → 保持已提交，用户看到驳回原因。
    """
    rid = int(data.get('id') or 0)
    approve = bool(data.get('approve'))
    note = str(data.get('note') or '').strip()[:200]
    if not rid:
        raise bad_request('缺少申请编号')
    row = db.one('SELECT * FROM withdraw_requests WHERE id = ?', (rid,))
    if not row:
        raise not_found('这条撤回申请不存在')
    if row['status'] != '待审批':
        raise bad_request('这条申请已经处理过了（当前状态：%s）' % row['status'])

    now = datex.now_str()
    with db.transaction() as conn:
        conn.execute('UPDATE withdraw_requests SET status = ?, decided_at = ?,'
                     ' decided_by = ?, decide_note = ? WHERE id = ?',
                     ('已同意' if approve else '已驳回', now,
                      admin_user['id'], note, rid))
        if approve:
            conn.execute("UPDATE entries SET status = '草稿', updated_at = ?"
                         ' WHERE user_id = ? AND period_start = ?',
                         (now, row['user_id'], row['period_start']))
    db.audit(admin_user['id'], 'withdraw_decide',
             '#%d %s %s' % (rid, '同意' if approve else '驳回',
                            row['period_start']))
    return {'id': rid, 'status': '已同意' if approve else '已驳回',
            'message': '已同意撤回，对方可以继续修改了' if approve
                       else '已驳回，该期保持已提交状态'}



def copy_prev_period(user, data):
    """把上一个周期的明细整体平移到本周期（跳过已填的日期）"""
    ps, pe = _resolve_period(data.get('periodStart') or data.get('weekStart'))
    _ensure_fillable(user, ps, pe)
    prev_ps, prev_pe = datex.prev_period(ps)
    src = load_period_entries(user['id'], prev_ps)
    if not src:
        raise not_found('上一个周期没有填报记录，无法复制')

    cur = load_period_entries(user['id'], ps)
    have_days = {e['date'] for e in cur}

    offset = (ps - prev_ps).days
    items = []
    for e in src:
        d = datex.add_days(datex.parse_ymd(e['date']), offset)
        if not (ps <= d <= pe):
            continue
        if d.isoformat() in have_days:
            continue
        items.append({'date': d.isoformat(), 'work_type': e['work_type'],
                      'kind': e.get('kind') or '正常',
                      'hours': e.get('hours') or 0,
                      'project_id': e['project_id'], 'content': e['content']})
    if not items:
        return {'periodStart': ps.isoformat(), 'copied': 0,
                'message': '本期已无空白日期可复制'}

    rows = _build_entry_rows(user, ps, pe, items, '草稿')
    with db.transaction() as conn:
        conn.executemany(_INSERT_SQL, rows)
    return {'periodStart': ps.isoformat(), 'copied': len(rows),
            'message': '已从上一周期复制 %d 条记录（草稿状态）' % len(rows)}


# ================================================================ 我的月度
def my_status(user, month_str=None):
    month = datex.normalize_month(month_str)
    info = datex.month_info(month)
    quota_hours = user['week_quota'] or config.WEEK_QUOTA_UNITS

    periods = []
    for ps, pe in datex.periods_for_month(month):
        pinfo = datex.period_info(ps, pe, quota_hours)
        rs = db.rows('SELECT status, rd_hours, nrd_hours FROM entries'
                     ' WHERE user_id = ? AND period_start = ?',
                     (user['id'], ps.isoformat()))
        submitted = bool(rs) and all(r['status'] == '已提交' for r in rs)
        hours = round(sum((r['rd_hours'] or 0) + (r['nrd_hours'] or 0) for r in rs), 1)
        editable, reason = _fill_state(user, ps, pe)
        periods.append({
            'periodStart': ps.isoformat(),
            'periodEnd': pe.isoformat(),
            'periodLabel': pinfo['label'],
            'dayCount': pinfo['day_count'],
            'extended': pinfo['extended'],
            'items': len(rs),
            'hours': hours,
            'submitted': submitted,
            'complete': bool(rs),
            'editable': editable,
            'ended': pe < date.today(),
            'lockReason': reason,
        })

    f_ps, f_pe = datex.fillable_period()
    return {
        'month': month, 'monthLabel': info['label'],
        'monthRange': info['range_label'], 'monthFullLabel': info['full_label'],
        'monthStart': info['start'].isoformat(), 'monthEnd': info['end'].isoformat(),
        'periods': periods,
        'totalHours': round(sum(p['hours'] for p in periods), 1),
        'totalItems': sum(p['items'] for p in periods),
        # 只把「已经过完还没提交」的算作待办；当前正在进行的那期不算，
        # 否则每周一都会提示"有 1 期未提交"，属于假待办。
        'pendingPeriods': [p['periodStart'] for p in periods
                           if p['ended'] and not p['submitted']],
        'fillablePeriodStart': f_ps.isoformat(),
        'fillablePeriodEnd': f_pe.isoformat(),
        'today': date.today().isoformat(),
    }


# ================================================================ 人员
def users_list(include_inactive=True):
    sql = 'SELECT * FROM users'
    if not include_inactive:
        sql += ' WHERE active = 1'
    items = db.rows(sql + ' ORDER BY role DESC, name')
    return [{
        'id': u['id'], 'username': u['username'], 'name': u['name'],
        'jobTitle': u['job_title'] or '', 'dept': u['dept'] or '',
        'role': u['role'], 'active': bool(u['active']),
        'personType': u.get('person_type') or config.PERSON_TYPE_RD,
        'trackHours': bool(u['track_hours']),
        'weekQuota': u['week_quota'],
        'mustChangePwd': bool(u['must_change_pwd']),
    } for u in items]


def save_user(data):
    from . import auth
    uid = int(data.get('id') or 0)
    username = str(data.get('username') or '').strip()
    name = str(data.get('name') or '').strip()
    if not username:
        raise bad_request('请填写登录账号')
    if not name:
        raise bad_request('请填写姓名')

    role = 'admin' if str(data.get('role') or '').strip() == 'admin' else 'member'
    person_type = str(data.get('personType') or '').strip()
    if person_type not in config.PERSON_TYPES:
        person_type = config.PERSON_TYPE_RD
    week_quota = int(data.get('weekQuota') or config.WEEK_QUOTA_UNITS)
    active = 1 if data.get('active', True) else 0
    track = 1 if data.get('trackHours', True) else 0

    if uid:
        dup = db.one('SELECT id FROM users WHERE username = ? AND id <> ?', (username, uid))
        if dup:
            raise bad_request('账号 %s 已被占用' % username)
        if role != 'admin':
            admins = db.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
                               ' AND id <> ?', (uid,))
            if admins == 0:
                raise bad_request('至少要保留一个启用的管理员账号')
        db.execute('UPDATE users SET username = ?, name = ?, job_title = ?, dept = ?,'
                   ' role = ?, person_type = ?, week_quota = ?, active = ?,'
                   ' track_hours = ?, updated_at = ?'
                   ' WHERE id = ?',
                   (username, name, str(data.get('jobTitle') or ''), str(data.get('dept') or ''),
                    role, person_type, week_quota, active, track, datex.now_str(), uid))
        return {'id': uid, 'updated': True}

    if db.one('SELECT id FROM users WHERE username = ?', (username,)):
        raise bad_request('账号 %s 已存在' % username)
    pwd = str(data.get('password') or '').strip() or '123456'
    if len(pwd) < 6:
        raise bad_request('初始密码至少 6 位')
    salt = auth.new_salt()
    nid = db.execute(
        'INSERT INTO users (username, name, job_title, dept, role, person_type,'
        ' password_hash, salt, week_quota, active, track_hours, must_change_pwd,'
        ' created_at, updated_at)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)',
        (username, name, str(data.get('jobTitle') or ''), str(data.get('dept') or ''),
         role, person_type, auth.hash_password(pwd, salt), salt, week_quota, active, track,
         datex.now_str(), datex.now_str()))
    return {'id': nid, 'created': True, 'password': pwd}


def reset_user_password(data):
    from . import auth
    uid = int(data.get('id') or 0)
    pwd = str(data.get('password') or '').strip() or '123456'
    if len(pwd) < 6:
        raise bad_request('新密码至少 6 位')
    if not db.one('SELECT id FROM users WHERE id = ?', (uid,)):
        raise not_found('用户不存在')
    auth.set_password(uid, pwd)
    db.execute('UPDATE users SET must_change_pwd = 1 WHERE id = ?', (uid,))
    return {'id': uid, 'password': pwd}


def import_users(rows):
    created = updated = 0
    errors = []
    for r in rows or []:
        try:
            username = str(r.get('username') or '').strip()
            name = str(r.get('name') or '').strip()
            if not username or not name:
                continue
            exist = db.one('SELECT * FROM users WHERE username = ?', (username,))
            payload = {
                'username': username, 'name': name,
                'jobTitle': r.get('jobTitle') or '',
                'dept': r.get('dept') or '',
                'role': 'admin' if str(r.get('role') or '') == 'admin' else 'member',
                'weekQuota': int(r.get('weekQuota') or config.WEEK_QUOTA_UNITS),
                'active': True, 'trackHours': True,
                'password': str(r.get('password') or '123456'),
            }
            if exist:
                payload['id'] = exist['id']
                save_user(payload)
                updated += 1
            else:
                save_user(payload)
                created += 1
        except ApiError as e:
            errors.append({'row': r, 'message': e.message})
    return {'created': created, 'updated': updated, 'errors': errors,
            'users': users_list()}


# ================================================================ 监控
def period_status(value=None):
    ps, pe = _resolve_period(value or datex.today_str())
    users = db.rows('SELECT * FROM users WHERE active = 1 AND track_hours = 1 ORDER BY name')
    out = []
    for u in users:
        info = datex.period_info(ps, pe, u['week_quota'])
        rs = db.rows('SELECT status, work_date, rd_hours, nrd_hours, hours'
                     ' FROM entries WHERE user_id = ? AND period_start = ?',
                     (u['id'], ps.isoformat()))
        days = len({r['work_date'] for r in rs})
        workdays = sum(1 for d in info['days'] if datex.is_workday(d))
        hours = round(sum((r['rd_hours'] or 0) + (r['nrd_hours'] or 0) for r in rs), 1)
        submitted = bool(rs) and all(r['status'] == '已提交' for r in rs)
        out.append({
            'userId': u['id'], 'name': u['name'], 'jobTitle': u['job_title'] or '',
            'days': days, 'workdays': workdays, 'items': len(rs),
            'hours': hours, 'submitted': submitted,
            'missing': days == 0,
            'incomplete': 0 < days < workdays,
            'rate': round(days / workdays * 100) if workdays else 0,
        })
    out.sort(key=lambda x: (x['days'], x['name']))
    info = datex.period_info(ps, pe)
    return {
        'periodStart': ps.isoformat(), 'periodEnd': pe.isoformat(),
        'periodLabel': info['label'], 'periodDays': info['day_count'],
        'total': len(out),
        'submittedCount': sum(1 for r in out if r['submitted']),
        'missingCount': sum(1 for r in out if r['missing']),
        'incompleteCount': sum(1 for r in out if r['incomplete']),
        'rows': out,
    }


def missing_members(value=None):
    data = period_status(value)
    miss = [r for r in data['rows'] if r['missing'] or r['incomplete'] or not r['submitted']]
    return {
        'periodStart': data['periodStart'], 'periodEnd': data['periodEnd'],
        'periodLabel': data['periodLabel'],
        'count': len(miss), 'names': '、'.join(r['name'] for r in miss),
        'members': miss,
    }


# ================================================================ 月度汇总
def month_summary(month_str=None, exclude_ids=None):
    """
    月度汇总。
    :param exclude_ids: 不纳入本次统计的人员 id 列表（例如误填人员），
                        人员汇总、工时构成、填报率都会相应重算。
    """
    month = datex.normalize_month(month_str)
    info = datex.month_info(month)
    excl = set()
    for x in (exclude_ids or []):
        try:
            excl.add(int(x))
        except (TypeError, ValueError):
            pass

    where = 'e.month = ? AND u.track_hours = 1'
    args = [month]
    if excl:
        where += ' AND e.user_id NOT IN (%s)' % ','.join('?' * len(excl))
        args += sorted(excl)

    sql = ("SELECT e.*, u.name AS u_name, u.job_title AS u_title, u.week_quota AS u_quota"
           ' FROM entries e JOIN users u ON u.id = e.user_id'
           ' WHERE ' + where +
           ' ORDER BY e.work_date, u.name, e.seq, e.id')
    records = db.rows(sql, tuple(args))

    detail = []
    per_person = {}
    per_project = {}
    project_people = set()
    rd_total = nrd_total = 0.0

    for r in records:
        nm = r['snap_name'] or r['u_name'] or ''
        ti = r['snap_title'] or r['u_title'] or ''
        wt = r['work_type']
        is_rd = (wt == '研发')
        hours = float(r.get('hours') or ((r['rd_hours'] or 0) + (r['nrd_hours'] or 0)))

        detail.append({
            'date': r['work_date'], 'name': nm, 'jobTitle': ti,
            'projectCode': (r['proj_code'] or '') if is_rd else EMPTY,
            'projectName': (r['proj_name'] or '') if is_rd else EMPTY,
            'rdHours': r['rd_hours'] or 0, 'nrdHours': r['nrd_hours'] or 0,
            'hours': hours,
            'content': r['content'] or '', 'workType': wt,
        })
        rd_total += (r['rd_hours'] or 0)
        nrd_total += (r['nrd_hours'] or 0)

        p = per_person.setdefault(r['user_id'], {
            'name': nm, 'jobTitle': ti, 'rd': 0.0, 'nrd': 0.0,
            'leave': 0.0, 'days': set(),
            'quotaDays': datex.month_workdays(month),
        })
        p['rd'] += (r['rd_hours'] or 0)
        p['nrd'] += (r['nrd_hours'] or 0)
        if datex.is_workday(datex.parse_ymd(r['work_date'])):
            p['days'].add(r['work_date'])
        if wt == '休假':
            p['leave'] += hours if hours else 0

        if is_rd:
            project_people.add(r['user_id'])
        code = (r['proj_code'] or '').strip()
        if code and code != EMPTY:
            key = (code, (r['proj_name'] or '未知项目'))
            pr = per_project.setdefault(key, {
                'code': key[0], 'name': key[1], 'rd': 0.0, 'nrd': 0.0,
                'people': set(), 'times': 0})
            pr['rd'] += (r['rd_hours'] or 0)
            pr['nrd'] += (r['nrd_hours'] or 0)
            pr['people'].add(r['user_id'])
            pr['times'] += 1

    for u in db.rows('SELECT * FROM users WHERE active = 1 AND track_hours = 1'):
        if u['id'] in excl:
            continue
        if u['id'] not in per_person:
            per_person[u['id']] = {
                'name': u['name'], 'jobTitle': u['job_title'] or '',
                'rd': 0.0, 'nrd': 0.0, 'leave': 0.0, 'days': set(),
                'quotaDays': datex.month_workdays(month),
            }

    person_rows = []
    for p in per_person.values():
        total = p['rd'] + p['nrd']
        person_rows.append({
            'name': p['name'], 'jobTitle': p['jobTitle'],
            'rd': round(p['rd'], 1), 'nrd': round(p['nrd'], 1),
            'total': round(total, 1),
            'leave': round(p['leave'], 1),
            'days': len(p['days']), 'quotaDays': p['quotaDays'],
            'rate': round(len(p['days']) / p['quotaDays'] * 100) if p['quotaDays'] else 0,
            'rdRatio': round(p['rd'] / total * 1000) / 10 if total else 0,
        })
    person_rows.sort(key=lambda x: x['name'])

    total_hours = rd_total + nrd_total
    project_rows = []
    for v in per_project.values():
        p_total = v['rd'] + v['nrd']
        project_rows.append({
            'code': v['code'], 'name': v['name'], 'people': len(v['people']),
            'rd': round(v['rd'], 1), 'nrd': round(v['nrd'], 1),
            'total': round(p_total, 1),
            'rdRatio': round(v['rd'] / p_total * 1000) / 10 if p_total else 0,
            'ratioOfMonthTotal': round(v['rd'] / total_hours * 1000) / 10 if total_hours else 0,
            'ratioOfMonthRd': round(v['rd'] / rd_total * 1000) / 10 if rd_total else 0,
            'times': v['times'],
        })
    project_rows.sort(key=lambda x: -x['rd'])

    quota_days_total = sum(p['quotaDays'] for p in person_rows)
    days_total = sum(p['days'] for p in person_rows)

    return {
        'month': month, 'monthLabel': info['label'],
        'monthRange': info['range_label'], 'monthFullLabel': info['full_label'],
        'monthStart': info['start'].isoformat(), 'monthEnd': info['end'].isoformat(),
        'cycleDays': info['cycle_days'],
        'detail': detail,
        'perPerson': person_rows, 'perProject': project_rows,
        'breakdown': {
            'rdHours': round(rd_total, 1), 'nrdHours': round(nrd_total, 1),
            'totalHours': round(total_hours, 1),
            'rdRatio': round(rd_total / total_hours * 1000) / 10 if total_hours else 0,
            'nrdRatio': round(nrd_total / total_hours * 1000) / 10 if total_hours else 0,
        },
        'stats': {
            'headcount': sum(1 for p in person_rows if p['total'] > 0),
            'memberCount': len(person_rows),
            'rows': len(detail),
            'rdTotal': round(rd_total, 1), 'nrdTotal': round(nrd_total, 1),
            'totalHours': round(total_hours, 1),
            'rdRatio': round(rd_total / total_hours * 1000) / 10 if total_hours else 0,
            'projectCount': len(project_rows),
            'projectPeople': len(project_people),
            'leaveTotal': round(sum(p['leave'] for p in person_rows), 1),
            'quotaDaysTotal': quota_days_total,
            'daysTotal': days_total,
            'fillRate': round(days_total / quota_days_total * 100) if quota_days_total else 0,
            'excludedCount': len(excl),
        },
        'excluded': sorted(excl),
    }


# ================================================================ 个人年度台账
def _system_first_month():
    """系统最早有工时记录的月份——用来界定「应填半天」从哪个月开始算"""
    r = db.one('SELECT MIN(month) AS m FROM entries')
    return (r['m'] if r and r.get('m') else None)


def _year_by_month(user_row, year):
    """
    按月汇总某人某年的工时（v1.3：按工作日天数算填写率，按小时算工时）。
    「应出勤」只统计「系统启用到当前月」之间的月份。
    """
    today = date.today()
    cur_ym = datex.month_key(today)     # 工资月口径：26 日及以后算下一个工资月
    first_ym = _system_first_month() or cur_ym

    months = []
    tot_rd = tot_nrd = tot_days = tot_workdays = tot_items = 0.0
    for m in range(1, 13):
        ym = '%04d-%02d' % (int(year), m)
        rs = db.rows('SELECT work_date, rd_hours, nrd_hours FROM entries'
                     ' WHERE user_id = ? AND month = ?', (user_row['id'], ym))
        rd = round(sum(r['rd_hours'] or 0 for r in rs), 1)
        nrd = round(sum(r['nrd_hours'] or 0 for r in rs), 1)
        items = len(rs)
        days = len({r['work_date'] for r in rs
                    if datex.is_workday(datex.parse_ymd(r['work_date']))})
        active = (ym >= first_ym) and ((ym <= cur_ym) or items > 0)
        workdays = datex.month_workdays(ym) if active else 0
        tot_rd += rd
        tot_nrd += nrd
        tot_days += days if active else 0
        tot_workdays += workdays
        tot_items += items
        months.append({
            'month': ym, 'label': '%d月' % m,
            'rd': rd, 'nrd': nrd, 'total': round(rd + nrd, 1),
            'items': items, 'days': days, 'workdays': workdays,
            'active': active,
            'rate': (min(100, round(days / workdays * 100)) if workdays else 0),
            'rdRatio': round(rd / (rd + nrd) * 1000) / 10 if (rd + nrd) else 0,
        })
    return months, {
        'rd': round(tot_rd, 1), 'nrd': round(tot_nrd, 1),
        'total': round(tot_rd + tot_nrd, 1),
        'days': int(tot_days), 'workdays': int(tot_workdays), 'items': int(tot_items),
        'rate': (min(100, round(tot_days / tot_workdays * 100)) if tot_workdays else 0),
        'rdRatio': round(tot_rd / (tot_rd + tot_nrd) * 1000) / 10
                   if (tot_rd + tot_nrd) else 0,
        'firstMonth': first_ym, 'currentMonth': cur_ym,
    }


def _year_projects(user_id, year):
    """个人年度项目分布（按工资月归属，不是按自然年 1/1~12/31）"""
    ym = '%04d-' % int(year)
    rs = db.rows(
        'SELECT proj_code, proj_name, rd_hours, month FROM entries'
        " WHERE user_id = ? AND month LIKE ? AND work_type = '研发'",
        (user_id, ym + '%'))
    agg = {}
    for r in rs:
        key = ((r['proj_code'] or '').strip() or '未编号', r['proj_name'] or '未知项目')
        cur = agg.setdefault(key, {'rd': 0, 'times': 0, 'months': set()})
        cur['rd'] += r['rd_hours']
        cur['times'] += 1
        cur['months'].add(r['month'])
    tot = sum(v['rd'] for v in agg.values())
    out = [{
        'code': k[0], 'name': k[1], 'rd': v['rd'], 'times': v['times'],
        'monthCount': len(v['months']),
        'ratio': round(v['rd'] / tot * 1000) / 10 if tot else 0,
    } for k, v in agg.items()]
    out.sort(key=lambda x: -x['rd'])
    return out


def year_ledger(year, user_id=None, current_user=None):
    """
    个人年度台账。
    - 普通用户只能看自己
    - 管理员可指定 userId 看任意人；不指定时返回全员年度汇总
    """
    year = int(year or date.today().year)
    is_admin = bool(current_user and current_user['role'] == 'admin')
    target_id = int(user_id or 0)

    if not is_admin:
        target_id = current_user['id']
    elif not target_id:
        return year_overview(year)

    u = db.one('SELECT * FROM users WHERE id = ?', (target_id,))
    if not u:
        raise not_found('用户不存在')

    months, totals = _year_by_month(u, year)
    return {
        'year': year,
        'userId': u['id'],
        'name': u['name'],
        'jobTitle': u['job_title'] or '',
        'dept': u['dept'] or '',
        'months': months,
        'totals': totals,
        'projects': _year_projects(u['id'], year),
        'mode': 'person',
    }


def year_overview(year):
    """全员年度汇总（管理员）"""
    year = int(year or date.today().year)
    users = db.rows('SELECT * FROM users WHERE active = 1 AND track_hours = 1 ORDER BY name')
    rows = []
    tot_rd = tot_nrd = tot_days = tot_workdays = 0
    for u in users:
        _, t = _year_by_month(u, year)
        tot_rd += t['rd']
        tot_nrd += t['nrd']
        tot_days += t['days']
        tot_workdays += t['workdays']
        rows.append({
            'userId': u['id'], 'name': u['name'], 'jobTitle': u['job_title'] or '',
            'dept': u['dept'] or '',
            'rd': t['rd'], 'nrd': t['nrd'], 'total': t['total'],
            'days': t['days'], 'workdays': t['workdays'],
            'rate': t['rate'], 'rdRatio': t['rdRatio'],
        })
    rows.sort(key=lambda x: (-x['total'], x['name']))
    return {
        'year': year, 'mode': 'overview', 'rows': rows,
        'totals': {
            'rd': round(tot_rd, 1), 'nrd': round(tot_nrd, 1),
            'total': round(tot_rd + tot_nrd, 1),
            'days': tot_days, 'workdays': tot_workdays,
            'rate': (min(100, round(tot_days / tot_workdays * 100)) if tot_workdays else 0),
            'rdRatio': round(tot_rd / (tot_rd + tot_nrd) * 1000) / 10
                       if (tot_rd + tot_nrd) else 0,
        },
    }


# ================================================================ 原始记录导出
def export_rows(params):
    """
    导出「每周每人的原始记录」用于留底。
    支持三种筛选：
      - month     : 按月份（如 2026-10）
      - period    : 按单个填报周期（传周期内任意日期）
      - from/to   : 按日期区间
    """
    where = ['1 = 1']
    args = []

    month = params.get('month')
    period = params.get('period') or params.get('periodStart')
    d_from = params.get('from')
    d_to = params.get('to')

    if period:
        ps, pe = _resolve_period(period)
        where.append('e.work_date BETWEEN ? AND ?')
        args += [ps.isoformat(), pe.isoformat()]
    elif month:
        ym = datex.normalize_month(month)
        mi = datex.month_info(ym)
        where.append('e.work_date BETWEEN ? AND ?')
        args += [mi['start'].isoformat(), mi['end'].isoformat()]
    elif d_from or d_to:
        start = datex.parse_ymd(d_from) if d_from else date(2000, 1, 1)
        end = datex.parse_ymd(d_to) if d_to else date(2099, 12, 31)
        where.append('e.work_date BETWEEN ? AND ?')
        args += [start.isoformat(), end.isoformat()]

    uid = int(params.get('userId') or 0)
    if uid:
        where.append('e.user_id = ?')
        args.append(uid)

    sql = ('SELECT e.*, u.username AS u_account, u.name AS u_name,'
           ' u.job_title AS u_title, u.dept AS u_dept'
           ' FROM entries e JOIN users u ON u.id = e.user_id'
           ' WHERE ' + ' AND '.join(where) +
           " ORDER BY e.work_date, u.name, e.seq, e.id")
    records = db.rows(sql, tuple(args))

    rows = []
    for i, r in enumerate(records, start=1):
        d = datex.parse_ymd(r['work_date'])
        hours = float(r.get('hours') or ((r['rd_hours'] or 0) + (r['nrd_hours'] or 0)))
        rows.append({
            'seq': i,
            'id': r['id'],
            'periodStart': r['period_start'] or '',
            'periodEnd': r['period_end'] or '',
            'date': r['work_date'],
            'weekday': datex.weekday_cn(d),
            'daySeq': (r.get('seq') or 0) + 1,
            'name': r['snap_name'] or r['u_name'] or '',
            'account': r['u_account'] or '',
            'jobTitle': r['snap_title'] or r['u_title'] or '',
            'dept': r['u_dept'] or '',
            'workType': r['work_type'],
            'projectCode': r['proj_code'] or '',
            'projectName': r['proj_name'] or '',
            'hours': hours,
            'rdHours': r['rd_hours'] or 0,
            'nrdHours': r['nrd_hours'] or 0,
            'content': r['content'] or '',
            'status': r['status'],
            'updatedAt': r['updated_at'] or '',
        })

    # 附加汇总（按人 / 按周期），方便留底时一起核对
    by_person = {}
    by_period = {}
    for r in rows:
        p = by_person.setdefault(r['name'],
                                 {'name': r['name'], 'rd': 0, 'nrd': 0, 'units': 0, 'hours': 0})
        p['rd'] += r['rdHours']
        p['nrd'] += r['nrdHours']
        p['hours'] += r['hours']
        p['units'] += 1
        pz = by_period.setdefault(r['periodStart'], {
            'periodStart': r['periodStart'], 'periodEnd': r['periodEnd'],
            'rd': 0, 'nrd': 0, 'units': 0, 'hours': 0})
        pz['rd'] += r['rdHours']
        pz['nrd'] += r['nrdHours']
        pz['hours'] += r['hours']
        pz['units'] += 1

    return {
        'rows': rows,
        'count': len(rows),
        'byPerson': sorted(by_person.values(), key=lambda x: x['name']),
        'byPeriod': sorted(by_period.values(), key=lambda x: x['periodStart']),
        'filter': {'month': month or '', 'period': period or '',
                   'from': d_from or '', 'to': d_to or '', 'userId': uid or ''},
        'generatedAt': datex.now_str(),
    }
