# -*- coding: utf-8 -*-
"""
填报校验规则（v1.3：明细条目模型）

原则：
  1. 尽可能减少麻烦——不再强制每天按 4+4 划分，一天可填多条目、工时随意；
  2. 尽可能保证真实性——不允许空置（每个工作日都要有记录），
     内容写清楚，研发必须挂项目；
  3. 合计工时只做提醒，不做拦截（加班、请假都能自然表达）。
"""
import re

from . import config, datex

_PUNCT = re.compile(r'[\s\u3000。，,、；;：:！!？?"\'“”‘’（）()\[\]【】\-—_~～.…/\\|]')

_VAGUE_CACHE = None


def compact(s):
    return _PUNCT.sub('', str(s or ''))


def _vague_set():
    global _VAGUE_CACHE
    if _VAGUE_CACHE is None:
        _VAGUE_CACHE = set(compact(w) for w in config.VAGUE_CONTENT)
    return _VAGUE_CACHE


def is_vague(content):
    c = compact(content)
    return (not c) or (c in _vague_set())


def check_content(content, min_len=None, check_vague=True, hint=None):
    """
    研发/非研发的内容校验

    :param min_len: 最少字数；None 用 config.MIN_CONTENT_LEN
    :param check_vague: 是否拦截模糊表述
    :param hint: 自定义提示语（辅助人员用）
    """
    s = str(content or '').strip()
    need = config.MIN_CONTENT_LEN if min_len is None else int(min_len)
    if not s:
        return '请填写具体工作内容'
    if len(s) < need:
        if hint:
            return '%s（至少 %d 个字）' % (hint, need)
        return ('工作内容至少 %d 个字，要写清做了什么'
                '（如"调试ADC采样滤波参数，完成3组对比测试"）' % need)
    if len(s) > config.MAX_CONTENT_LEN:
        return '工作内容不超过 %d 个字' % config.MAX_CONTENT_LEN
    if check_vague and is_vague(s):
        return '「%s」属于模糊表述，请写具体做了什么、完成什么结果' % s
    return None


def check_leave_content(content):
    """休假也要写清真实情况（年假/病假/调休…），字数要求更低、不做模糊词拦截"""
    s = str(content or '').strip()
    if not s:
        return '休假也要写清情况（如"年假""病假""调休半天"）'
    if len(s) < config.LEAVE_MIN_CONTENT_LEN:
        return '休假情况至少 %d 个字' % config.LEAVE_MIN_CONTENT_LEN
    if len(s) > config.MAX_CONTENT_LEN:
        return '内容不超过 %d 个字' % config.MAX_CONTENT_LEN
    return None


def normalize_work_type(wt):
    s = str(wt or '').strip()
    if s in ('研发', 'rd', 'RD', 'R&D'):
        return '研发'
    if s in ('非研发', 'nrd', 'NRD', '非研发工时'):
        return '非研发'
    if s in ('休假', '请假', 'leave', 'LEAVE', '休'):
        return '休假'
    return ''


def normalize_kind(k):
    s = str(k or '').strip()
    if s in ('加班', 'ot', 'OT', 'overtime'):
        return '加班'
    return '正常'


def normalize_hours(v, work_type=None):
    """休假一律 0；其余取 0~MAX_DAILY_HOURS 的小数（一位小数）"""
    if work_type == '休假':
        return 0.0
    try:
        h = float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0
    if h < 0:
        return 0.0
    return round(min(h, float(config.MAX_DAILY_HOURS)), 1)


def normalize_slot(slot):
    """兼容老数据：上午/下午（新模型不再使用，仅导出时参考）"""
    s = str(slot or '').strip().lower()
    if s in ('下午', 'pm', 'p'):
        return '下午'
    return '上午'


def validate_entries(entries, allowed_days, project_ids, require_full_days=True,
                     person_type=None):
    """
    校验一个填报周期的明细条目

    :param entries: [{date, work_type, hours, project_id, content, kind}]
    :param allowed_days: 本周期允许的日期（date 对象列表）
    :param project_ids: 可挂项目的 id 集合
    :param require_full_days: 是否要求每个工作日都有记录（默认 True）
    :param person_type: 人员性质；辅助人员的「非研发」条目按更宽松的字数校验，
                        研发条目仍按研发标准（研发要进费用归集，内容不能太潦草）
    :return: (ok, errors, stat)
    """
    errors = []
    allowed = list(allowed_days or [])
    allowed_set = set(allowed)
    is_aux = (str(person_type or '').strip() == config.PERSON_TYPE_AUX)

    by_day = {}
    rd_total = 0.0
    nrd_total = 0.0

    for idx, raw in enumerate(entries or []):
        d = datex.parse_ymd(raw.get('date'))
        where = d.isoformat()

        if d not in allowed_set:
            errors.append({'path': where, 'field': 'date', 'index': idx,
                           'message': '%s 不在本次填报周期内' % where})
            continue

        wt = normalize_work_type(raw.get('work_type'))
        content = str(raw.get('content') or '').strip()
        hours = normalize_hours(raw.get('hours'), wt)

        if not wt:
            if content or hours:
                errors.append({'path': where, 'field': 'work_type', 'index': idx,
                               'message': '%s 有一条记录没选类型（研发/非研发/休假）' % where})
            continue

        if wt != '休假' and hours <= 0:
            errors.append({'path': where, 'field': 'hours', 'index': idx,
                           'message': '%s 工时必须大于 0（没上班请选「休假」）' % where})

        if wt == '休假':
            err = check_leave_content(content)
        elif is_aux and wt == '非研发':
            # 辅助人员干的是行政事务，内容本来就短，按放宽后的规则
            err = check_content(
                content,
                min_len=getattr(config, 'AUX_NRD_MIN_CONTENT_LEN', 2),
                check_vague=getattr(config, 'AUX_NRD_CHECK_VAGUE', True),
                hint='工作内容至少 2 个字，如"盘库""整理合同""收发快递"')
        else:
            err = check_content(content)
        if err:
            errors.append({'path': where, 'field': 'content', 'index': idx,
                           'message': '%s %s' % (where, err)})

        if wt == '研发':
            pid = raw.get('project_id')
            if pid in (None, '', 0, '0'):
                errors.append({'path': where, 'field': 'project', 'index': idx,
                               'message': '%s 研发工时必须选择研发项目' % where})
            else:
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    pid = None
                if pid not in project_ids:
                    errors.append({'path': where, 'field': 'project', 'index': idx,
                                   'message': '%s 所选项目已停用或不存在，请重新选择' % where})

        by_day.setdefault(d, []).append({'type': wt, 'hours': hours})
        if wt == '研发':
            rd_total += hours
        elif wt == '非研发':
            nrd_total += hours

    # 单日工时上限
    for d, items in by_day.items():
        day_hours = sum(i['hours'] for i in items)
        if day_hours > config.MAX_DAILY_HOURS:
            errors.append({'path': d.isoformat(), 'field': 'hours', 'index': None,
                           'message': '%s 合计 %g 小时，超过单日上限 %g 小时'
                                      % (d.isoformat(), day_hours, config.MAX_DAILY_HOURS)})

    # 不允许空置：每个工作日都要有记录
    workdays = [d for d in allowed if datex.is_workday(d)]
    missing = [d for d in workdays if d not in by_day]
    if require_full_days and missing:
        names = '、'.join(d.strftime('%m-%d') for d in missing[:8])
        more = ' 等 %d 天' % len(missing) if len(missing) > 8 else ''
        errors.append({
            'path': missing[0].isoformat(), 'field': 'day', 'index': None,
            'message': ('有 %d 个工作日还没填（%s%s）。休假也请选「休假」并写清原因'
                        % (len(missing), names, more)),
        })

    stat = {
        'daysWithEntry': len(by_day),
        'workdays': len(workdays),
        'totalHours': round(rd_total + nrd_total, 1),
        'rdHours': round(rd_total, 1),
        'nrdHours': round(nrd_total, 1),
        'maxDailyHours': config.MAX_DAILY_HOURS,
    }
    return (not errors), errors, stat
