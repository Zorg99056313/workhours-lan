# -*- coding: utf-8 -*-
"""日期与工作日历工具（纯标准库，纯日历运算，不受时区影响）"""
from datetime import date, datetime, timedelta
from . import config

WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
WEEKDAY_SHORT = ['一', '二', '三', '四', '五', '六', '日']

_HOLIDAYS = set(config.HOLIDAYS or [])
_EXTRA = set(config.EXTRA_WORKDAYS or [])


def today_str():
    return date.today().isoformat()


def parse_ymd(s):
    """把多种写法统一成 date；失败返回今天"""
    if not s:
        return date.today()
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    t = str(s).strip()[:10].replace('/', '-').replace('.', '-')
    try:
        y, m, d = t.split('-')
        return date(int(y), int(m), int(d))
    except Exception:
        return date.today()


def ymd(d):
    return d.isoformat()


def add_days(d, n):
    return d + timedelta(days=n)


def week_start(d):
    """本周一"""
    return d - timedelta(days=d.weekday())


def week_days(ws):
    return [ws + timedelta(days=i) for i in range(7)]


def is_weekend(d):
    return d.weekday() >= 5


def is_workday(d):
    s = d.isoformat()
    if s in _EXTRA:
        return True
    if s in _HOLIDAYS:
        return False
    return d.weekday() < 5


def expected_units_for_week(ws, week_quota=None):
    """一周应填的半天数：真实工作日 × (quota/5)，遇节假日自动扣减"""
    quota = week_quota if week_quota is not None else config.WEEK_QUOTA_UNITS
    per_day = quota / 5.0
    workdays = sum(1 for d in week_days(ws) if is_workday(d))
    return int(round(workdays * per_day))


# ================================================================ 填报周期
# 需求：本月前几天或后几天可能不在完整的一周内，需要把这几天的格子也放进
#      同一张填报表里，保证月度统计不漏天。做法是把自然周按月切分，
#      再把「零碎的跨月片段」（默认 ≤ 3 天）并入相邻的那个周期。
#      合并后一个周期可能超过 7 天（最长约 13 天），表格照着多显示几行即可。

def _natural_week_groups(start, end):
    """把 [start, end] 按自然周（周一~周日）切成若干组，只保留区间内的日期"""
    groups = []
    d = start
    while d <= end:
        ws = week_start(d)
        we = add_days(ws, 6)
        g_start = max(ws, start)
        g_end = min(we, end)
        groups.append((g_start, g_end))
        d = add_days(g_end, 1)
    return groups


def _is_broken(g_start, g_end):
    """是不是"被切过"的周（不是完整自然周）"""
    return g_start.weekday() != 0 or g_end != add_days(g_start, 6)


def _span_days(g_start, g_end):
    return (g_end - g_start).days + 1


def periods_for_month(ym):
    """
    把一个自然月划分成若干「填报周期」（相邻、不重叠、正好覆盖整月）

    规则：
      1. 按月内的自然周切片；
      2. 末片段（跨到下个月的那几天）若 ≤ PERIOD_TAIL_MERGE_DAYS 天 → 并入前一个周期；
      3. 首片段（从本月 1 日开始、接着上个月的那几天）若 ≤ PERIOD_HEAD_MERGE_DAYS 天 → 并入后一个周期。

    例：某月 28 日是周日，29/30/31 是周一到周三 → 这 3 天并入 22~28 那一周，
        该周期变成 22~31 共 10 天，填报表就多显示 3 天。
    """
    info = month_info(ym)
    groups = _natural_week_groups(info['start'], info['end'])
    tail_max = int(getattr(config, 'PERIOD_TAIL_MERGE_DAYS', 3))
    head_max = int(getattr(config, 'PERIOD_HEAD_MERGE_DAYS', 3))

    # 末片段并入前一组
    if len(groups) >= 2:
        gs, ge = groups[-1]
        if _is_broken(gs, ge) and _span_days(gs, ge) <= tail_max:
            p_gs, _ = groups[-2]
            groups[-2] = (p_gs, ge)
            groups.pop()

    # 首片段并入后一组
    if len(groups) >= 2:
        gs, ge = groups[0]
        if _is_broken(gs, ge) and _span_days(gs, ge) <= head_max:
            _, n_ge = groups[1]
            groups[0] = (gs, n_ge)
            groups.pop(1)

    return groups


def period_days(p_start, p_end):
    out = []
    d = p_start
    while d <= p_end:
        out.append(d)
        d += timedelta(days=1)
    return out


def period_info(p_start, p_end=None, week_quota=None):
    """周期信息：起止、天数、工作日数、应填半天数"""
    if p_end is None:
        p_start, p_end = period_of_date(p_start)
    quota = week_quota if week_quota is not None else config.WEEK_QUOTA_UNITS
    per_day = quota / 5.0
    days = period_days(p_start, p_end)
    workdays = sum(1 for d in days if is_workday(d))
    m = month_key(p_start)
    return {
        'start': p_start,
        'end': p_end,
        'days': days,
        'day_count': len(days),
        'workdays': workdays,
        'quota': int(round(workdays * per_day)),
        'month': m,
        'label': '%s ~ %s' % (p_start.isoformat(), p_end.isoformat()) if len(days) > 1
                 else p_start.isoformat(),
        'extended': len(days) > 7,
        'month_label': month_info(m)['label'],
        'iso_week': p_start.isocalendar()[1],
    }


def period_of_date(d):
    """给定任意日期，返回它所属填报周期的 (start, end)"""
    ym = month_key(d)
    for gs, ge in periods_for_month(ym):
        if gs <= d <= ge:
            return gs, ge
    ws = week_start(d)
    return ws, add_days(ws, 6)


def expected_units_for_period(p_start, p_end=None, week_quota=None):
    return period_info(p_start, p_end, week_quota)['quota']


def period_ended(p_end, d=None):
    """这个周期是不是已经过完了（结束日早于今天）

    「下周填本周」的口径：周期最后一天过完，第二天才允许填。
    例：周期 10-26 ~ 11-01，则 11-02 起可填。
    """
    d = d or date.today()
    return p_end < d


def fillable_period(d=None):
    """最近一个「已经过完」的周期 —— 正常打开填报页时应停在这里

    如果今天所在的周期已经结束（比如今天是周日，周期到周日），就返回本期；
    否则返回上一期（因为本期还没过完，不该现在填）。
    """
    d = d or date.today()
    ps, pe = period_of_date(d)
    if pe < d:
        return ps, pe
    return prev_period(ps)


def fillable_from(p_end):
    """这个周期从哪天起可以填（结束日的第二天）"""
    return add_days(p_end, 1)



def prev_period(p_start):
    return period_of_date(add_days(p_start, -1))


def next_period(p_end):
    return period_of_date(add_days(p_end, 1))


def periods_of_year(year):
    out = []
    for m in range(1, 13):
        out.append('%04d-%02d' % (int(year), m))
    return out


def cycle_start_day():
    """工资月的起始日：26 表示「上月26日~当月25日」；1 表示自然月"""
    try:
        d = int(getattr(config, 'MONTH_CYCLE_START_DAY', 1) or 1)
    except (TypeError, ValueError):
        d = 1
    return d if 1 <= d <= 28 else 1


def month_key(d):
    """
    date -> 它属于哪个「工资月」的 'YYYY-MM'

    MONTH_CYCLE_START_DAY = 26 时：
      2026-05-25 -> '2026-05'     2026-05-26 -> '2026-06'
      2026-12-26 -> '2027-01'     2027-01-25 -> '2027-01'
    """
    day = cycle_start_day()
    if day > 1 and d.day >= day:
        if d.month == 12:
            return '%04d-01' % (d.year + 1)
        return '%04d-%02d' % (d.year, d.month + 1)
    return d.strftime('%Y-%m')


def month_range(ym):
    """工资月的起止（含）→ (start_date, end_date)"""
    y, m = int(ym[:4]), int(ym[5:7])
    day = cycle_start_day()
    if day <= 1:
        start = date(y, m, 1)
        end = (date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
        return start, end
    # 起始 = 上个月的第 day 天；结束 = 本月第 (day-1) 天
    pm_y, pm_m = (y - 1, 12) if m == 1 else (y, m - 1)
    return date(pm_y, pm_m, day), date(y, m, day - 1)


def month_range_label(ym):
    """'5月26日-6月25日' 这种口径说明，跨年时带上年份"""
    s, e = month_range(ym)
    if s.year != e.year:
        return '%d年%d月%d日 - %d年%d月%d日' % (s.year, s.month, s.day,
                                                e.year, e.month, e.day)
    return '%d月%d日 - %d月%d日' % (s.month, s.day, e.month, e.day)


def normalize_month(s):
    """'2026-10' / '2026/10' / '202610' / '2026年10月' / date → 'YYYY-MM'"""
    if not s:
        return month_key(date.today())
    if isinstance(s, (date, datetime)):
        return month_key(s)
    t = str(s).strip().replace('/', '-').replace('年', '-').replace('月', '')
    parts = [p for p in t.replace('.', '-').split('-') if p]
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        m = int(parts[1])
        if 1 <= m <= 12:
            return '%04d-%02d' % (int(parts[0]), m)
    if len(t) == 6 and t.isdigit():
        m = int(t[4:])
        if 1 <= m <= 12:
            return '%s-%s' % (t[:4], t[4:])
    return month_key(date.today())


def month_info(ym):
    """
    返回该「工资月」的起止、天数、日期列表、标签。

    MONTH_CYCLE_START_DAY = 26 时：
      2026-06 -> 2026-05-26 ~ 2026-06-25（31 天）
    """
    ym = normalize_month(ym)
    y, m = int(ym[:4]), int(ym[5:7])
    start, end = month_range(ym)
    nxt = end + timedelta(days=1)
    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return {
        'month': ym,
        'label': '%d年%d月' % (y, m),
        'start': start,
        'end': end,
        'next_start': nxt,
        'days': days,
        'days_in_month': len(days),
        'cycle_days': len(days),
        'range_label': month_range_label(ym),
        'cycle_start_day': cycle_start_day(),
        'full_label': '%d年%d月（%s）' % (y, m, month_range_label(ym)),
    }



def week_starts_in_month(ym):
    info = month_info(ym)
    seen = []
    for d in info['days']:
        ws = week_start(d)
        if ws not in seen:
            seen.append(ws)
    return seen


def month_quota_for_week(ws, info, week_quota=None):
    """某个周落在本月内的应填半天数（跨月周只算本月部分）"""
    quota = week_quota if week_quota is not None else config.WEEK_QUOTA_UNITS
    per_day = quota / 5.0
    workdays = sum(
        1 for d in week_days(ws)
        if info['start'] <= d <= info['end'] and is_workday(d)
    )
    return int(round(workdays * per_day))


def month_quota_total(ym, week_quota=None):
    info = month_info(ym)
    return sum(month_quota_for_week(ws, info, week_quota) for ws in week_starts_in_month(ym))


def iso_week_no(d):
    return d.isocalendar()[1]


def weekday_cn(d):
    return WEEKDAY_CN[d.weekday()]


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def month_workdays(ym):
    """该月的工作日数（已扣法定节假日）"""
    return sum(1 for d in month_info(ym)['days'] if is_workday(d))
