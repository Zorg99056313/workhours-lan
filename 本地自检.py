# -*- coding: utf-8 -*-
"""
本地端到端自检（v1.3 明细条目模型）
运行：python 本地自检.py
"""
import json
import re
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TMP = os.path.join(BASE, '_selftest_tmp')
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

from app import config  # noqa: E402

config.DB_PATH = os.path.join(TMP, 'test.db')
config.OUTPUT_DIR = os.path.join(TMP, 'out')
config.BACKUP_DIR = os.path.join(TMP, 'bak')
config.DATA_DIR = TMP
for d in (config.OUTPUT_DIR, config.BACKUP_DIR):
    os.makedirs(d, exist_ok=True)


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


config.PORT = _free_port()
config.HOST = '127.0.0.1'
config.AUTO_OPEN_BROWSER = False
config.FEISHU_WEBHOOK = ''
config.ADMIN_DEFAULT_PASSWORD = 'admin123456'
# 自检要能填历史任意周期，先关掉「必须等周期结束」的时间窗；
# 第 18 节会再打开它，专门验证这条规则本身（这样断言与运行当天的日期无关）。
config.FILL_REQUIRE_PERIOD_ENDED = False

from app import db, httpd  # noqa: E402

PASS = FAIL = 0
FAILED = []


def check(cond, name, extra=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  \u2705 %s' % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print('  \u274c %s%s' % (name, ('  -> ' + str(extra)) if extra is not None else ''))


BASE_URL = 'http://127.0.0.1:%d' % config.PORT


def call(method, path, body=None, token=None, raw=None, ctype=None):
    url = BASE_URL + path
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers['Content-Type'] = ctype or 'application/octet-stream'
    elif body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        headers['X-Token'] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = r.read()
            if 'application/json' in r.headers.get('Content-Type', ''):
                return r.status, json.loads(payload.decode('utf-8'))
            return r.status, payload
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode('utf-8'))
        except Exception:
            return e.code, payload


MONTH = '2026-10'
PROJECTS = [('RD-2026-01', '控制器固件优化'), ('RD-2026-02', '低功耗通信协议'),
            ('RD-2026-03', '电源模块热设计')]
PEOPLE = [('lina', '李娜', '嵌入式工程师', 6.0),
          ('wangqiang', '王强', '硬件工程师', 4.0),
          ('zhaomin', '赵敏', '软件工程师', 8.0)]
RD_TEXT = ['调试RD-01的ADC采样滤波参数，完成3组对比测试',
           '实现LoRa休眠唤醒握手流程，待机电流从2.1mA降至0.8mA',
           '完成MOS管温升仿真，最高结温由128℃降至105℃',
           '重构串口中断服务程序，中断响应时间由18us降至9us']
NRD_TEXT = ['参加部门周会与项目进度对齐，输出风险项3条',
            '协助生产部分析产线烧录良率问题，定位为治具接触不良']


def build_items(days, pids, rd_hours=6.0, seed=0):
    items = []
    k = 0
    for day in days:
        ds = day['date']
        if not day['isWorkday']:
            items.append({'date': ds, 'work_type': '休假', 'hours': 0,
                          'content': '周末休息', 'project_id': '', 'kind': '正常'})
            continue
        items.append({'date': ds, 'work_type': '研发', 'hours': rd_hours,
                      'project_id': pids[(seed + k) % len(pids)],
                      'content': RD_TEXT[(seed + k) % len(RD_TEXT)], 'kind': '正常'})
        rest = round(8.0 - rd_hours, 1)
        if rest > 0:
            items.append({'date': ds, 'work_type': '非研发', 'hours': rest,
                          'project_id': '',
                          'content': NRD_TEXT[(seed + k) % len(NRD_TEXT)], 'kind': '正常'})
        k += 1
    return items


def main():
    db.init_db()
    srv = httpd.serve()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)

    print('\n=== 0. 服务与登录 ===')
    code, r = call('GET', '/api/ping')
    check(code == 200 and r.get('ok'), 'ping 正常')
    code, r = call('POST', '/api/login', {'username': 'admin', 'password': 'x'})
    check(code == 401, '错误密码被拒绝')
    code, r = call('POST', '/api/login',
                   {'username': config.ADMIN_DEFAULT_USERNAME,
                    'password': config.ADMIN_DEFAULT_PASSWORD})
    check(code == 200 and r.get('token') and r['user']['isAdmin'], '管理员登录成功')
    admin = r['token']
    code, r = call('GET', '/api/admin/users')
    check(code == 401, '未登录访问管理接口被拒绝')

    print('\n=== 1. 建人员 / 项目 ===')
    tokens = {}
    for un, nm, job, _h in PEOPLE:
        code, r = call('POST', '/api/admin/user/save',
                       {'username': un, 'name': nm, 'jobTitle': job, 'dept': '技术中心',
                        'role': 'member', 'weekQuota': 10, 'password': 'pass123456'}, admin)
        check(code == 200, '创建人员 %s' % nm, r)
        code, r = call('POST', '/api/login', {'username': un, 'password': 'pass123456'})
        check(code == 200, '%s 登录成功' % nm)
        tokens[un] = r['token']

    code, r = call('POST', '/api/admin/project/import',
                   {'text': '\n'.join('%s\t%s\t研发' % p for p in PROJECTS)}, admin)
    check(code == 200 and r['data']['created'] == 3, '导入 3 个项目')
    projects = call('GET', '/api/projects', token=tokens['lina'])[1]['projects']
    pids = [p['id'] for p in projects]

    print('\n=== 2. 工资月口径 + 填报周期（跨周）===')
    # 工资月：上月26日 ~ 当月25日。2026-06 = 05-26 ~ 06-25
    code, r = call('GET', '/api/ping')
    check(r.get('monthCycleStartDay') == 26, '服务端下发工资月起始日 = 26',
          r.get('monthCycleStartDay'))
    from app import datex
    m0, m1 = datex.month_range('2026-06')
    check((m0.isoformat(), m1.isoformat()) == ('2026-05-26', '2026-06-25'),
          '2026年6月 = 2026-05-26 ~ 2026-06-25', (m0, m1))
    check(datex.month_key(datex.parse_ymd('2026-05-25')) == '2026-05',
          '5月25日算 5 月（工资月最后一天）')
    check(datex.month_key(datex.parse_ymd('2026-05-26')) == '2026-06',
          '5月26日算 6 月')
    check(datex.month_key(datex.parse_ymd('2026-06-25')) == '2026-06',
          '6月25日算 6 月')
    check(datex.month_key(datex.parse_ymd('2026-06-26')) == '2026-07',
          '6月26日算 7 月')
    check(datex.month_key(datex.parse_ymd('2026-12-26')) == '2027-01',
          '12月26日算下一年 1 月（跨年正确）')
    check(datex.month_info('2026-06')['range_label'] == '5月26日 - 6月25日',
          '口径说明文案', datex.month_info('2026-06')['range_label'])

    # 2024-01-29 属于工资月 2024-02（01-26 ~ 02-25），首片段 3 天并入后一期
    code, r = call('GET', '/api/period?periodStart=2024-01-29', token=tokens['lina'])
    p = r['data']
    check(p['periodStart'] == '2024-01-26' and p['periodEnd'] == '2024-02-04',
          '2024-01-29 归属周期 01-26~02-04（首片段并入）',
          (p['periodStart'], p['periodEnd']))
    check(p['periodDays'] == 10, '周期展开 %d 天' % p['periodDays'])
    check(len(p['days']) == 10, '返回 %d 天明细' % len(p['days']))
    check(all('items' in d for d in p['days']), '每天返回 items 明细数组')

    print('\n=== 3. 周末/节假日自动预填休假 ===')
    code, r = call('GET', '/api/period?periodStart=2026-10-19', token=tokens['lina'])
    d = r['data']
    wd = [x for x in d['days'] if not x['isWorkday']]
    workdays = [x for x in d['days'] if x['isWorkday']]
    check(len(wd) >= 2, '本周有 %d 个休息日' % len(wd))
    check(all(x['items'] and x['items'][0]['work_type'] == '休假' for x in wd),
          '休息日自动预填「休假」')
    check(all(x['items'][0]['hours'] == 0 for x in wd), '休息日休假工时为 0')
    check(all(x['items'][0]['work_type'] == '' for x in workdays),
          '工作日默认空白待填（%d 天）' % len(workdays))

    print('\n=== 4. 一天多条明细（研发6h + 会议2h）===')
    first_day = workdays[0]['date']
    items = [{'date': first_day, 'work_type': '研发', 'hours': 6,
              'project_id': pids[0], 'content': '调试ADC采样滤波参数完成3组对比',
              'kind': '正常'},
             {'date': first_day, 'work_type': '非研发', 'hours': 2,
              'project_id': '', 'content': '参加部门周会与项目进度对齐',
              'kind': '正常'}]
    for x in workdays[1:]:
        items.append({'date': x['date'], 'work_type': '研发', 'hours': 8,
                      'project_id': pids[0], 'content': '重构串口中断服务程序',
                      'kind': '正常'})
    for x in wd:
        items.append({'date': x['date'], 'work_type': '休假', 'hours': 0,
                      'content': '周末休息', 'project_id': '', 'kind': '正常'})

    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': items}, tokens['lina'])
    check(code == 200, '一天两条明细保存成功（6h+2h）', r.get('message') if code != 200 else '')
    if code == 200:
        dd = r['data']
        check(dd['items'] == len(items), '保存 %d 条明细' % dd['items'])
        check(dd['totalHours'] == 5 * 8, '本期合计 %g 小时（5 天 × 8h）' % dd['totalHours'])

    code, r = call('GET', '/api/period?periodStart=2026-10-19', token=tokens['lina'])
    day1 = [x for x in r['data']['days'] if x['date'] == first_day][0]
    check(len(day1['items']) == 2, '当天返回 %d 条明细' % len(day1['items']))
    check(sorted([i['work_type'] for i in day1['items']]) == ['研发', '非研发'],
          '两条明细类型正确（研发/非研发）')
    hrs = sorted([i['hours'] for i in day1['items']])
    check(hrs == [2, 6], '工时分别 6h / 2h，不强制 4+4')

    print('\n=== 5. 校验：不允许空置 ===')
    short = [i for i in items if i['date'] != workdays[1]['date']]
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': short}, tokens['lina'])
    check(code == 422, '少填一天被拒绝')
    check(any(e['field'] == 'day' for e in r['details']['errors']), '错误提示指向未填日期')
    check('还没填' in r['details']['errors'][0]['message'], '提示语说明哪几天没填',
          r['details']['errors'][0]['message'])

    print('\n=== 6. 校验：研发必挂项目 / 工时必须>0 / 模糊表述 ===')
    bad = json.loads(json.dumps(items))
    bad[0]['project_id'] = ''
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': bad}, tokens['lina'])
    check(code == 422, '研发未选项目被拒绝')

    bad = json.loads(json.dumps(items))
    bad[0]['hours'] = 0
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': bad}, tokens['lina'])
    check(code == 422, '工时 0 被拒绝（没上班请选休假）')

    bad = json.loads(json.dumps(items))
    bad[0]['content'] = '研发工作'
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': bad}, tokens['lina'])
    check(code == 422, '模糊表述被拒绝')

    print('\n=== 7. 加班：超过 8 小时不拦截 ===')
    ot = json.loads(json.dumps(items))
    ot.append({'date': workdays[0]['date'], 'work_type': '研发', 'hours': 3,
               'project_id': pids[0], 'content': '加班调试固件死机问题',
               'kind': '加班'})
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': ot}, tokens['lina'])
    check(code == 200, '一天 8h + 加班 3h = 11h 允许保存', r.get('message'))
    if code == 200:
        check(r['data']['totalHours'] == 5 * 8 + 3, '合计 %g 小时' % r['data']['totalHours'])
        check(r['data']['warning'] and '比常规出勤' in (r['data']['warning'] or ''),
              '给出"比常规多"的提醒', r['data']['warning'])

    print('\n=== 8. 休假：内容必填、工时自动 0 ===')
    lv = json.loads(json.dumps(items))
    for x in lv:
        if x['work_type'] == '休假':
            x['content'] = ''
            break
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': lv}, tokens['lina'])
    check(code == 422, '休假不写原因被拒绝')

    lv2 = json.loads(json.dumps(items))
    for x in lv2:
        if x['work_type'] == '休假':
            x['hours'] = 8
            break
    code, r = call('POST', '/api/period/save',
                   {'periodStart': '2026-10-19', 'items': lv2}, tokens['lina'])
    check(code == 200 and r['data']['totalHours'] == 40,
          '休假即使填了 8 小时也按 0 计（合计 %g）' % r['data'].get('totalHours'))

    print('\n=== 9. 提交 / 申请撤回 / 复制上期 ===')
    code, r = call('POST', '/api/period/submit', {'periodStart': '2026-10-19'}, tokens['lina'])
    check(code == 200 and r['data']['submitted'], '提交成功')
    code, r = call('GET', '/api/period?periodStart=2026-10-19', token=tokens['lina'])
    check(r['data']['submitted'], '提交状态可读回')

    # v1.5.2：普通成员不能直接撤回，只能申请（需管理员审批）
    code, r = call('POST', '/api/period/withdraw',
                   {'periodStart': '2026-10-19',
                    'reason': '自检：需要复核本期工时'}, tokens['lina'])
    check(code == 200 and (r.get('data') or {}).get('status') == '待审批',
          '成员撤回变成「申请撤回」', (code, r))
    if code != 200:
        return
    wait_id = r['data']['requestId']
    code, r = call('POST', '/api/admin/withdraw-decide',
                   {'id': wait_id, 'approve': True, 'note': '自检放行'}, admin)
    check(code == 200, '管理员同意该申请')
    code, r = call('GET', '/api/period?periodStart=2026-10-19', token=tokens['lina'])
    check(r['data']['submitted'] is False, '审批同意后变回草稿')

    code, r = call('POST', '/api/period/copy-prev',
                   {'periodStart': '2026-10-26'}, tokens['lina'])
    check(code == 200 and r['data']['copied'] > 0, '从上一期复制 %s 条' % r['data'].get('copied'))

    print('\n=== 10. 填满整月（3 人 × 全部周期）===')
    st0 = call('GET', '/api/my-status?month=' + MONTH, token=tokens['lina'])[1]['data']
    month_periods = [x['periodStart'] for x in st0['periods']]
    check(len(month_periods) >= 4, '2026-10 共 %d 个周期' % len(month_periods))
    # 工资月 2026-10 = 09-26 ~ 10-25，各周期必须连续覆盖且不超出
    check(st0['monthStart'] == '2026-09-26' and st0['monthEnd'] == '2026-10-25',
          '2026年10月区间 = 09-26 ~ 10-25', (st0['monthStart'], st0['monthEnd']))
    check(st0['periods'][0]['periodStart'] == st0['monthStart']
          and st0['periods'][-1]['periodEnd'] == st0['monthEnd'],
          '首尾周期与工资月对齐')
    gaps = [i for i in range(len(st0['periods']) - 1)
            if st0['periods'][i]['periodEnd'] >= st0['periods'][i + 1]['periodStart']]
    check(not gaps, '周期之间无重叠', gaps)
    okc = 0
    for un, nm, job, rd_h in PEOPLE:
        for wi, ps in enumerate(month_periods):
            dd = call('GET', '/api/period?periodStart=' + ps, token=tokens[un])[1]['data']
            its = build_items(dd['days'], pids, rd_hours=rd_h, seed=wi)
            code, r = call('POST', '/api/period/save',
                           {'periodStart': ps, 'items': its, 'submit': True}, tokens[un])
            if code == 200:
                okc += 1
            else:
                print('    ! %s %s: %s' % (nm, ps, r.get('message')))
    want_ok = 3 * len(month_periods)
    check(okc == want_ok, '%d 次提交全部成功（%d）' % (want_ok, okc))

    code, r = call('GET', '/api/my-status?month=' + MONTH, token=tokens['lina'])
    st = r['data']
    check(st['totalHours'] > 0, '李娜本月 %g 小时 / %d 条' % (st['totalHours'], st['totalItems']))
    check(len(st['pendingPeriods']) == 0, '本月全部已提交')

    print('\n=== 11. 监控与权限 ===')
    code, r = call('GET', '/api/admin/period-status?periodStart=2026-10-19', token=admin)
    check(code == 200 and r['data']['total'] == 3, '监控覆盖 3 人')
    check(all('days' in x and 'hours' in x for x in r['data']['rows']), '监控行含天数与工时')
    code, r = call('GET', '/api/admin/users', token=tokens['lina'])
    check(code == 403, '普通用户访问管理接口被拒绝')

    print('\n=== 12. 月度统计 ===')
    code, r = call('GET', '/api/admin/preview?month=' + MONTH, token=admin)
    pv = r['data']
    bd = pv['breakdown']
    check(code == 200, '预览正常')
    check(pv['stats']['totalHours'] > 0, '总工时 %g' % pv['stats']['totalHours'])
    check(abs(pv['stats']['rdTotal'] + pv['stats']['nrdTotal'] - pv['stats']['totalHours']) < 0.01,
          '研发+非研发 = 总工时')
    check(pv['stats']['fillRate'] == 100, '填写率 %s%%（按天数）' % pv['stats']['fillRate'])
    check(all('days' in x and 'quotaDays' in x for x in pv['perPerson']), '人员汇总含天数口径')

    code, r = call('POST', '/api/admin/report', {'month': MONTH}, admin)
    check(code == 200 and r['data']['fileName'], '一键生成成功')
    gen = r['data']
    code, data = call('GET', gen['downloadUrl'], token=admin)
    check(code == 200 and isinstance(data, bytes) and len(data) > 5000, '下载 Excel 成功')
    xp = os.path.join(TMP, 'r.xlsx')
    open(xp, 'wb').write(data)

    print('\n=== 13. 回读 Excel ===')
    import datetime
    import openpyxl
    wb = openpyxl.load_workbook(xp)
    check(wb.sheetnames == ['工时明细', '人员汇总', '项目汇总', '填报周期'],
          '4 个 Sheet：%s' % wb.sheetnames)
    ws1 = wb['工时明细']
    hdr = [ws1.cell(1, c).value for c in range(1, 11)]
    check(hdr[:8] == config.DETAIL_HEADERS[:8], '前 8 列与参考表一致', hdr[:8])
    check(hdr[8] == '工时类型' and hdr[9] == '当日合计工时', '追加 2 列：%s' % hdr[8:])
    widths = [round(ws1.column_dimensions[chr(64 + i)].width, 2) for i in range(1, 9)]
    check(widths == [13.16, 9.08, 16.12, 17.23, 17.97, 13.16, 15.19, 50.78],
          '前 8 列列宽与参考表一致')
    f1 = ws1.cell(1, 1).font
    check(f1.name == 'Microsoft YaHei' and f1.size == 11 and f1.bold, '表头字体正确')
    d1 = ws1.cell(2, 1).value
    check(isinstance(d1, datetime.datetime), '日期为真实日期')
    types = set(ws1.cell(r_, 9).value for r_ in range(2, ws1.max_row + 1))
    check(types <= {'研发', '非研发', '休假', '—'}, '工时类型列取值合理：%s' % types)

    ws2 = wb['人员汇总']
    h2 = [ws2.cell(2, c).value for c in range(1, 10)]
    check(h2 == ['姓名', '岗位', '研发工时', '非研发工时', '合计工时', '研发占比',
                 '应出勤天数', '实填天数', '填写率'], '人员汇总表头（9 列，无加班）：%s' % h2)
    check(ws2.cell(ws2.max_row, 9).value == 1, '合计填写率 100%')

    ws3 = wb['项目汇总']
    tot3 = None
    for r_ in range(3, ws3.max_row + 1):
        if ws3.cell(r_, 1).value == '合计':
            tot3 = r_
            break
    check(tot3 is not None, '项目汇总有合计行')
    if tot3:
        v = [ws3.cell(tot3, c).value for c in range(1, 10)]
        check(abs(v[3] - bd['rdHours']) < 0.01, '合计研发工时 = %s' % v[3])
        check(v[4] == 0, '项目非研发工时恒为 0')
        check(abs(v[6] - 1.0) < 0.001, '研发工时占比 %.0f%%' % (v[6] * 100))
        check(abs(v[7] - bd['rdRatio'] / 100.0) < 0.001,
              '占全月工时比例 %.1f%%（= 全月研发占比）' % (v[7] * 100))

    print('\n=== 14. 人员勾选 ===')
    code, r = call('GET', '/api/admin/users', token=admin)
    lina_id = [u['id'] for u in r['users'] if u['username'] == 'lina'][0]
    code, base = call('GET', '/api/admin/preview?month=' + MONTH, token=admin)
    code, r = call('GET', '/api/admin/preview?month=%s&excludeUserIds=%s' % (MONTH, lina_id), token=admin)
    ex = r['data']
    check(lina_id in ex['excluded'], '排除参数生效')
    check(ex['stats']['headcount'] == base['data']['stats']['headcount'] - 1, '覆盖人数 -1')
    check(all(p['name'] != '李娜' for p in ex['perPerson']), '被排除者不在人员汇总')
    check(len(ex['members']) == base['data']['stats']['memberCount'], '返回可勾选人员清单')

    print('\n=== 15. 年度台账 ===')
    code, r = call('GET', '/api/year?year=2026', token=tokens['lina'])
    y = r['data']
    check(code == 200 and y['mode'] == 'person', '个人年度台账')
    check(len(y['months']) == 12, '12 个月')
    check(y['totals']['rate'] <= 100, '全年填报率 %s%% 不超过 100' % y['totals']['rate'])
    code, r = call('GET', '/api/year?year=2026', token=admin)
    check(r['data']['mode'] == 'overview', '管理员看到全员汇总')
    code, data = call('GET', '/api/year/export?year=2026', token=tokens['lina'])
    check(code == 200 and isinstance(data, bytes), '年度台账导出成功')

    print('\n=== 16. 原始记录导出 ===')
    code, r = call('GET', '/api/admin/export/raw?month=%s&format=json' % MONTH, token=admin)
    exr = r['data']
    check(code == 200 and exr['count'] > 0, '导出 %d 条原始记录' % exr['count'])
    r0 = exr['rows'][0]
    need = ['periodStart', 'periodEnd', 'date', 'weekday', 'daySeq', 'name', 'workType',
            'hours', 'rdHours', 'nrdHours', 'content', 'status', 'updatedAt']
    check(all(k in r0 for k in need), '字段完整（%d 个，不含加班属性）' % len(need))
    check('kind' not in r0, '原始记录不再有 kind（加班属性）字段')
    code, data = call('GET', '/api/admin/export/raw?month=%s&format=xlsx' % MONTH, token=admin)
    check(code == 200 and isinstance(data, bytes), '原始记录 Excel 导出成功')
    code, data = call('GET', '/api/admin/export/raw?month=%s&format=csv' % MONTH, token=admin)
    check(code == 200 and data[:3] == b'\xef\xbb\xbf', 'CSV 带 UTF-8 BOM')

    print('\n=== 17. 其他 ===')
    code, data = call('GET', '/api/admin/backup', token=admin)
    check(code == 200 and len(data) > 1000, '数据库备份下载')
    code, html = call('GET', '/')
    check(code == 200 and '研发工时' in html.decode('utf-8', 'replace'), '首页可访问')
    code, js = call('GET', '/app.js')
    check(code == 200 and len(js) > 30000, 'app.js 可访问（%d 字节）' % len(js))

    print('\n=== 18. 填报时间窗（下周填本周）===')
    _check_fill_window(tokens, admin, pids)

    print('\n=== 19. 人员性质（辅助人员自动预填）===')
    _check_aux_person(admin, pids, tokens)

    print('\n=== 20. 提交后锁定 + 撤回审批 ===')
    _check_submit_lock(tokens, admin, pids)

    # 服务器在这里关闭，之后的小节都不再发 HTTP 请求
    srv.shutdown()

    print('\n=== 21. 启动/运维脚本 ===')
    _check_bats()
    _check_stop_script()
    _check_launcher_importable()
    _check_server_source()

    print('\n=== 22. 工资月口径迁移（老数据自动升级）===')
    _check_month_migration()

    print('\n=== 23. 前端交互（下拉/输入/弹窗锁定）===')
    _check_frontend_interaction()

    print('\n=== 24. 加班统计已移除 / 长项目名显示 ===')
    _check_overtime_removed()
    _check_long_name_display()


def _check_submit_lock(tokens, admin, pids):
    """已提交的数据不能自己改，必须管理员审批同意撤回才能改（v1.5.2）。

    注意：本函数会改写 lina 的 2026-10-19 那期状态，放在最后跑。
    """
    ps = '2026-10-19'

    def build(tok, content='调试ADC采样滤波参数完成对比测试'):
        dd = call('GET', '/api/period?periodStart=' + ps, token=tok)[1]['data']
        out = []
        for x in dd['days']:
            if not x['isWorkday']:
                out.append({'date': x['date'], 'work_type': '休假', 'hours': 0,
                            'content': '周末休息', 'project_id': '', 'kind': '正常'})
            else:
                out.append({'date': x['date'], 'work_type': '研发', 'hours': 8,
                            'project_id': pids[0], 'content': content, 'kind': '正常'})
        return out

    # 先确保这一期是已提交
    code, _ = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': build(tokens['lina']), 'submit': True},
                   tokens['lina'])
    code, r = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    d = r['data']
    check(d['submitted'] is True, '周期处于已提交状态')
    check(d['canEdit'] is False, '已提交时 canEdit=False', d.get('canEdit'))

    # 先记下当前真实内容，被拒绝后再比对，确认一个字都没被改
    code, before = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    before_txt = before['data']['days'][0]['items'][0]['content']

    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': build(tokens['lina'], '偷偷改内容')},
                   tokens['lina'])
    check(code == 422, '成员直接覆盖已提交数据被拒绝（HTTP %s）' % code)
    check(isinstance(r, dict) and r.get('code') == 'PERIOD_SUBMITTED',
          '错误码为 PERIOD_SUBMITTED', r.get('code') if isinstance(r, dict) else r)
    check(isinstance(r, dict) and '申请撤回' in (r.get('message') or ''),
          '提示语引导走撤回申请')

    code, r = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    after_txt = r['data']['days'][0]['items'][0]['content']
    check(after_txt == before_txt, '被拒绝后数据没有被改动',
          (before_txt, after_txt))

    # 申请撤回必须写原因
    code, _ = call('POST', '/api/period/withdraw', {'periodStart': ps}, tokens['lina'])
    check(code == 400, '不写撤回原因被拒绝')
    code, r = call('POST', '/api/period/withdraw',
                   {'periodStart': ps, 'reason': '项目经理要求补录非研发工时'},
                   tokens['lina'])
    check(code == 200 and r['data']['status'] == '待审批', '撤回申请已提交')
    rid = r['data']['requestId']
    code, r2 = call('POST', '/api/period/withdraw',
                    {'periodStart': ps, 'reason': '重复申请'}, tokens['lina'])
    check(code == 200 and r2['data']['requestId'] == rid, '重复申请不新建单据')

    code, r = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    check(r['data']['withdrawPending'] is not None, '页面显示待审批申请')
    check(r['data']['canEdit'] is False, '待审批期间仍不可编辑')

    # 审批权限
    code, r = call('GET', '/api/admin/withdraw-requests', token=admin)
    check(code == 200 and any(x['id'] == rid for x in r['data']['requests']),
          '管理员能看到该申请')
    code, _ = call('GET', '/api/admin/withdraw-requests', token=tokens['zhaomin'])
    check(code == 403, '普通成员访问审批接口 403')

    # 驳回
    code, r = call('POST', '/api/admin/withdraw-decide',
                   {'id': rid, 'approve': False, 'note': '本月报表已报送'}, admin)
    check(code == 200 and r['data']['status'] == '已驳回', '驳回成功')
    code, r = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    check(r['data']['submitted'] is True and r['data']['canEdit'] is False,
          '驳回后仍锁定')
    check((r['data']['lastWithdrawResult'] or {}).get('status') == '已驳回',
          '用户能看到驳回结果')

    # 再申请 → 同意
    code, r = call('POST', '/api/period/withdraw',
                   {'periodStart': ps, 'reason': '确实填错了，需要更正'},
                   tokens['lina'])
    check(code == 200, '驳回后可再次申请')
    rid2 = r['data']['requestId']
    code, r = call('POST', '/api/admin/withdraw-decide',
                   {'id': rid2, 'approve': True, 'note': '已核实'}, admin)
    check(code == 200 and r['data']['status'] == '已同意', '同意成功')
    code, r = call('GET', '/api/period?periodStart=' + ps, token=tokens['lina'])
    check(r['data']['submitted'] is False, '同意后变回草稿')
    check(r['data']['canEdit'] is True, '同意后可以编辑')

    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': build(tokens['lina']), 'submit': True},
                   tokens['lina'])
    check(code == 200, '同意后可修改并重新提交', r.get('message') if code != 200 else '')

    code, _ = call('POST', '/api/admin/withdraw-decide',
                   {'id': rid2, 'approve': True}, admin)
    check(code == 400, '同一条申请不能重复审批')

    # 管理员不受此限制（补录纠错）
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': build(admin), 'submit': True}, admin)
    check(code == 200, '管理员可覆盖自己的已提交数据（补录用）',
          r.get('message') if code != 200 else '')


def _check_overtime_removed():
    """加班统计已移除（v1.5.2）：接口和报表都不再有加班字段。"""
    with open(os.path.join(BASE, 'app', 'service.py'), encoding='utf-8') as f:
        svc = f.read()
    check('ot_total' not in svc, 'service 里不再累计加班工时')
    check("'ot'" not in svc and "'otTotal'" not in svc,
          'service 不再返回 ot / otTotal 字段')
    with open(os.path.join(BASE, 'app', 'report.py'), encoding='utf-8') as f:
        rep = f.read()
    check('加班工时' not in rep, '报表里不再有「加班工时」列')
    check('工时属性' not in rep, '原始导出不再有「工时属性」列')
    with open(os.path.join(BASE, 'app', 'static', 'app.js'), encoding='utf-8') as f:
        js = f.read()
    check('otTotal' not in js, '前端不再引用 otTotal')


def _check_long_name_display():
    """长项目名：视觉上换行，但数据不截断（v1.5.2）。"""
    with open(os.path.join(BASE, 'app', 'static', 'app.js'), encoding='utf-8') as f:
        js = f.read()
    with open(os.path.join(BASE, 'app', 'static', 'app.css'), encoding='utf-8') as f:
        css = f.read()
    check('function nameCell(' in js, '有 nameCell 辅助函数')
    check('white-space:normal' in css and 'name-cell' in css,
          'CSS 允许长名称换行')
    check('word-break:break-word' in css, 'CSS 长单词也换行')
    check("title=\"' + esc(t)" in js or "title='" in js,
          '单元格带 title（悬停看全称）')
    # 下拉里的省略号只是显示，数据仍从 projects 取原值
    check('short' in js and 'slice(0, 25)' in js,
          '下拉选项做了显示截断（带 title 全称）')


def _check_frontend_interaction():
    """前端交互的三处修复（都是真实踩过的坑，做静态断言防回归）。

    坑1：项目下拉点不开，要按住拖到框里才能选
         → <select>/<input> 也带 data-act，被 box.onclick 的 closest 捕获，
           每次点击都 renderDays() 重建整个 DOM，原生下拉被销毁。
    坑2：输入工作内容时光标自动跳出
         → 同一个原因：DOM 被重建，输入框是新元素，焦点丢失。
    坑3：后台弹窗点空白处就关，填的内容全作废
         → mask.onclick 只要 e.target === mask 就关，没有不可关的开关。
    """
    js_path = os.path.join(BASE, 'app', 'static', 'app.js')
    css_path = os.path.join(BASE, 'app', 'static', 'app.css')
    with open(js_path, encoding='utf-8') as f:
        js = f.read()
    with open(css_path, encoding='utf-8') as f:
        css = f.read()

    # --- 坑1：下拉不能被当成按钮 ---
    m = re.search(r"isRd \? '<select([^>]*)>'", js)
    check(bool(m), '找到项目下拉的生成代码')
    if m:
        attrs = m.group(1)
        check('data-act' not in attrs, '项目下拉不再带 data-act')
        check('data-proj' in attrs, '项目下拉改用 data-proj')
    check("el.closest('input,select,textarea,option')" in js,
          'click 处理器跳过 input/select/textarea/option')
    check('BUTTON_ACTS' in js and 'if (!BUTTON_ACTS[act0]) return;' in js,
          '只有按钮动作才触发重绘（白名单）')

    # --- 坑2：输入框不能失焦 ---
    check('data-field="hours"' in js and 'data-act="hours"' not in js,
          '工时输入框改用 data-field（不再被当按钮）')
    check('data-field="content"' in js and 'data-act="content"' not in js,
          '内容输入框改用 data-field（不再被当按钮）')
    check("t.getAttribute('data-field')" in js, 'oninput 按 data-field 分派')
    check("meta.getAttribute('data-v') !== s" in js and
          "num.getAttribute('data-v') !== numTxt" in js,
          '汇总文字变化才重写 DOM（避免逐字重排）')

    # --- 坑3：弹窗可锁定 ---
    check('opt.lockable' in js, 'modal 支持 lockable')
    check('mdlLock' in js, '弹窗头部有锁定按钮')
    check('if (!force && locked)' in js, '锁定后 close 被拦截')
    check('window.confirm' in js and 'dirty' in js, '已输入内容时点遮罩先二次确认')
    check('.modal-lock' in css and '.modal-lock.on' in css, 'CSS 有锁定按钮样式')
    n_lock = len(re.findall(r'lockable: true', js))
    check(n_lock >= 5, '至少 5 个填写型弹窗启用 lockable（%d）' % n_lock)

    # --- 既有功能未被破坏 ---
    check('data-act="rd"' in js and 'data-act="nrd"' in js
          and 'data-act="leave"' in js and 'data-act="del"' in js,
          '类型/删除按钮的 data-act 保留')
    check('[data-add],[data-act]' in js, '只读模式仍会隐藏按钮')


def _check_aux_person(admin, pids, tokens):
    """辅助人员：工作日自动预填「非研发 8 小时 + 部门行政管理事务」，且可手动改"""
    # 1) 建一个辅助人员
    code, r = call('POST', '/api/admin/user/save',
                   {'username': 'aux01', 'name': '王行政', 'jobTitle': '行政专员',
                    'dept': '综合部', 'role': 'member', 'personType': '辅助人员',
                    'weekQuota': 10, 'password': 'pass123456'}, admin)
    check(code == 200, '建辅助人员账号', r)
    db.execute("UPDATE users SET must_change_pwd = 0 WHERE username = 'aux01'")
    code, r = call('POST', '/api/login',
                   {'username': 'aux01', 'password': 'pass123456'})
    tok = r['token']
    check(r['user'].get('personType') == '辅助人员',
          '登录返回 personType=辅助人员', r['user'].get('personType'))

    # 2) 人员列表能读回性质
    code, r = call('GET', '/api/admin/users', token=admin)
    u = [x for x in r['users'] if x['username'] == 'aux01'][0]
    check(u.get('personType') == '辅助人员', '人员列表回读人员性质', u.get('personType'))

    # 3) 预填内容
    ps = '2026-10-19'
    code, p = call('GET', '/api/period?periodStart=' + ps, token=tok)
    d = p['data']
    check(d.get('isAux') is True, 'isAux 标记为真', d.get('isAux'))
    wd = [x for x in d['days'] if x['isWorkday']]
    check(all(x['items'][0]['work_type'] == '非研发' for x in wd),
          '%d 个工作日预填「非研发」' % len(wd),
          [(x['date'], x['items'][0]['work_type']) for x in wd])
    check(all(float(x['items'][0]['hours'] or 0) == 8 for x in wd),
          '预填工时均为 8 小时',
          [(x['date'], x['items'][0]['hours']) for x in wd])
    check(all(x['items'][0]['content'] == '部门行政管理事务' for x in wd),
          '预填内容均为「部门行政管理事务」',
          [(x['date'], x['items'][0]['content']) for x in wd])

    # 4) 周末仍是休假（且带内容，可直接提交）
    off = [x for x in d['days'] if not x['isWorkday']]
    check(all(x['items'][0]['work_type'] == '休假'
              and x['items'][0]['content'] for x in off),
          '%d 个休息日预填「休假」且带说明' % len(off),
          [(x['date'], x['items'][0]['content']) for x in off])

    # 5) 不改直接提交（提交后用「管理员审批撤回」再改，符合新流程）
    items = []
    for x in d['days']:
        for it in x['items']:
            items.append({'date': x['date'], 'work_type': it['work_type'],
                          'hours': it['hours'], 'content': it['content'],
                          'project_id': '', 'kind': '正常'})
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': items, 'submit': True}, tok)
    check(code == 200, '辅助人员不改可直接提交', r.get('message') if code != 200 else '')
    if code == 200:
        check(r['data']['totalHours'] == 8.0 * len(wd),
              '合计 %g 小时 = 工作日×8' % (8.0 * len(wd)), r['data']['totalHours'])
        check(r['data']['rdHours'] == 0, '研发工时 0（不混进研发归集）',
              r['data']['rdHours'])

    # 已提交后不能直接改（新规则），先走一次撤回审批再继续测「可手动调整」
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': items}, tok)
    check(code == 422, '提交后辅助人员也不能直接覆盖', code)
    code, r = call('POST', '/api/period/withdraw',
                   {'periodStart': ps, 'reason': '自检需要继续修改'}, tok)
    if code == 200:
        call('POST', '/api/admin/withdraw-decide',
             {'id': r['data']['requestId'], 'approve': True}, admin)

    # 6) 手动修改权限：类型 / 内容 / 工时 都能改（此时为草稿状态）
    mod = [dict(x) for x in items]
    for m in mod:
        if m['date'] == wd[0]['date']:
            m['work_type'] = '研发'
            m['project_id'] = pids[0]
            m['content'] = '协助调试控制器固件并输出测试结论'
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': mod}, tok)
    check(code == 200, '可把某天改成「研发」并挂项目', r.get('message') if code != 200 else '')
    if code == 200:
        check(r['data']['rdHours'] == 8, '改后研发工时 8', r['data']['rdHours'])

    mod2 = [dict(x) for x in items]
    for m in mod2:
        if m['date'] == wd[1]['date']:
            m['content'] = '协助仓库盘点并核对入库单据'
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': mod2}, tok)
    check(code == 200, '可改工作内容', r.get('message') if code != 200 else '')

    mod3 = [dict(x) for x in items]
    for m in mod3:
        if m['date'] == wd[2]['date']:
            m['hours'] = 11
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': mod3}, tok)
    check(code == 200, '可改工时为 11（超 8 小时按正常工时计）',
          r.get('message') if code != 200 else '')

    mod4 = [dict(x) for x in items]
    for m in mod4:
        if m['date'] == wd[3]['date']:
            m['work_type'] = '休假'
            m['hours'] = 0
            m['content'] = '事假'
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': mod4}, tok)
    check(code == 200, '可把某天改成「休假」', r.get('message') if code != 200 else '')

    # 7) 切回研发人员后，预填消失
    uid = u['id']
    code, _ = call('POST', '/api/admin/user/save',
                   {'id': uid, 'username': 'aux01', 'name': '王行政',
                    'jobTitle': '行政专员', 'dept': '综合部', 'role': 'member',
                    'personType': '研发人员', 'weekQuota': 10,
                    'active': True, 'trackHours': True}, admin)
    check(code == 200, '把辅助人员改回研发人员')
    code, p2 = call('GET', '/api/period?periodStart=2026-11-02', token=tok)
    check(p2['data'].get('isAux') is False, '切换后 isAux=False')
    wd2 = [x for x in p2['data']['days'] if x['isWorkday']]
    check(all(not x['items'][0]['work_type'] for x in wd2),
          '切换后不再预填', [x['items'][0]['work_type'] for x in wd2])

    # 8) 非法人员性质回落到研发人员
    code, _ = call('POST', '/api/admin/user/save',
                   {'id': uid, 'username': 'aux01', 'name': '王行政',
                    'jobTitle': '行政专员', 'dept': '综合部', 'role': 'member',
                    'personType': '不存在的类型', 'weekQuota': 10,
                    'active': True, 'trackHours': True}, admin)
    code, r = call('GET', '/api/admin/users', token=admin)
    u2 = [x for x in r['users'] if x['username'] == 'aux01'][0]
    check(u2.get('personType') == '研发人员', '非法人员性质回落到研发人员',
          u2.get('personType'))

    # 9) 辅助人员的非研发内容放宽到 2 字（研发条目仍 6 字）
    call('POST', '/api/admin/user/save',
         {'id': uid, 'username': 'aux01', 'name': '王行政',
          'jobTitle': '行政专员', 'dept': '综合部', 'role': 'member',
          'personType': '辅助人员', 'weekQuota': 10,
          'active': True, 'trackHours': True}, admin)

    def build_with(tok, first_type, first_content, pid=None):
        dd = call('GET', '/api/period?periodStart=%s' % ps, token=tok)[1]['data']
        out, first = [], True
        for x in dd['days']:
            if not x['isWorkday']:
                out.append({'date': x['date'], 'work_type': '休假', 'hours': 0,
                            'content': '周末休息', 'project_id': '', 'kind': '正常'})
                continue
            if first:
                first = False
                if first_type == '休假':
                    out.append({'date': x['date'], 'work_type': '休假', 'hours': 0,
                                'content': first_content, 'project_id': '',
                                'kind': '正常'})
                else:
                    out.append({'date': x['date'], 'work_type': first_type, 'hours': 8,
                                'content': first_content,
                                'project_id': (pid or '') if first_type == '研发' else '',
                                'kind': '正常'})
            else:
                out.append({'date': x['date'], 'work_type': '非研发', 'hours': 8,
                            'content': '协助处理日常行政事务工作', 'project_id': '',
                            'kind': '正常'})
        return out

    def msgs(r):
        return [e.get('message', '')
                for e in ((r.get('details') or {}).get('errors') or [])]

    for txt in ('盘库', '收发快递'):
        code, r = call('POST', '/api/period/save',
                       {'periodStart': ps, 'items': build_with(tok, '非研发', txt)},
                       tok)
        check(code == 200, '辅助人员非研发写「%s」通过（放宽到 2 字）' % txt, msgs(r))

    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps, 'items': build_with(tok, '非研发', '库')}, tok)
    check(code == 422 and any('至少 2 个字' in m for m in msgs(r)),
          '辅助人员写 1 个字仍被拦', msgs(r))

    for txt in ('工作', '其他'):
        code, r = call('POST', '/api/period/save',
                       {'periodStart': ps, 'items': build_with(tok, '非研发', txt)}, tok)
        check(code == 422 and any('模糊表述' in m for m in msgs(r)),
              '辅助人员写「%s」仍按模糊表述被拦' % txt, msgs(r))

    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps,
                    'items': build_with(tok, '研发', '调试', pids[0])}, tok)
    check(code == 422 and any('至少 6 个字' in m for m in msgs(r)),
          '辅助人员的研发条目仍要求 6 字', msgs(r))
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps,
                    'items': build_with(tok, '研发',
                                        '协助调试控制器固件并输出测试结论', pids[0])},
                   tok)
    check(code == 200, '辅助人员的研发条目写够 6 字可通过', msgs(r))

    # 研发人员不受影响
    # 注意：前面第 20 节已把这一期提交了，已提交状态下保存会被
    # PERIOD_SUBMITTED 拦住（不是内容校验），所以先由管理员代其撤回成草稿。
    lina_id = [u['id'] for u in
               call('GET', '/api/admin/users', token=admin)[1]['users']
               if u['username'] == 'lina'][0]
    call('POST', '/api/period/withdraw', {'periodStart': ps, 'userId': lina_id}, admin)
    code, r = call('POST', '/api/period/save',
                   {'periodStart': ps,
                    'items': build_with(tokens['lina'], '非研发', '盘库')},
                   tokens['lina'])
    check(code == 422 and any('至少 6 个字' in m for m in msgs(r)),
          '研发人员的非研发写「盘库」仍被拦（规则未变）', (code, msgs(r)))


def _check_month_migration():
    """老库（自然月口径）在口径改为「上月26日~当月25日」后能自动重算 month / 周期。

    同时验证明细记录不会丢，且重复启动不会反复改动（幂等）。
    """
    import threading as _th

    from app import datex, db

    old_path = config.DB_PATH
    new_path = os.path.join(TMP, 'mig.db')
    if os.path.exists(new_path):
        os.remove(new_path)
    try:
        config.DB_PATH = new_path
        db._local = _th.local()          # 丢掉旧连接缓存，改用新库
        conn = db.connect()
        conn.executescript(db.SCHEMA)
        conn.execute(
            'INSERT INTO users (username, name, job_title, role, password_hash, salt,'
            ' week_quota, active, track_hours, must_change_pwd, created_at, updated_at)'
            " VALUES ('mig','迁移测试','工程师','member','x','y',10,1,1,0,'2026-01-01','2026-01-01')")
        uid = conn.execute("SELECT id FROM users WHERE username='mig'").fetchone()[0]

        # 老口径：month 与周期都按自然月算（故意写成旧值）
        legacy = [
            ('2026-05-25', '2026-05', '2026-05-25', '2026-05-31'),
            ('2026-05-28', '2026-05', '2026-05-25', '2026-05-31'),
            ('2026-06-25', '2026-06', '2026-06-22', '2026-06-28'),
            ('2026-12-26', '2026-12', '2026-12-21', '2026-12-27'),
        ]
        for wd, mth, ps, pe in legacy:
            conn.execute(
                'INSERT INTO entries (user_id, work_date, seq, work_type, work_kind,'
                ' project_id, hours, rd_hours, nrd_hours, content, period_start,'
                ' period_end, month, status, snap_name, snap_title, proj_code,'
                ' proj_name, updated_at)'
                " VALUES (?,?,0,'研发','正常',NULL,8,8,0,'迁移测试用的工作内容描述',"
                "?,?,?,'已提交','迁移测试','工程师','RD-01','某项目','2026-01-01')",
                (uid, wd, ps, pe, mth))
        conn.commit()
        n_before = conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0]

        db.init_db()                      # 触发迁移
        rows = db.rows('SELECT work_date, month, period_start, period_end'
                       ' FROM entries ORDER BY work_date')
        check(len(rows) == n_before, '迁移后记录条数不变（%d）' % n_before, len(rows))

        want = {'2026-05-25': '2026-05', '2026-05-28': '2026-06',
                '2026-06-25': '2026-06', '2026-12-26': '2027-01'}
        badm = [r['work_date'] for r in rows if r['month'] != want.get(r['work_date'])]
        check(not badm, '每条日期都归到正确的工资月', badm)

        badp = []
        for r in rows:
            groups = datex.periods_for_month(r['month'])
            ok_g = any(g[0].isoformat() == r['period_start']
                       and g[1].isoformat() == r['period_end'] for g in groups)
            if not ok_g or not (r['period_start'] <= r['work_date'] <= r['period_end']):
                badp.append(r['work_date'])
        check(not badp, '周期已按新口径重算且包含当天', badp)

        snap = [(r['work_date'], r['month'], r['period_start']) for r in rows]
        db.init_db()                      # 再跑一次，应无变化
        rows2 = db.rows('SELECT work_date, month, period_start FROM entries'
                        ' ORDER BY work_date')
        check(snap == [(r['work_date'], r['month'], r['period_start']) for r in rows2],
              '重复启动不会反复改动数据（幂等）')

        # 按新口径汇总，确认数据落到正确的月份
        from app import service
        s6 = service.month_summary('2026-06')
        check(s6['stats']['rows'] == 2, '2026-06 命中 05-28 与 06-25 两条',
              s6['stats']['rows'])
        s1 = service.month_summary('2027-01')
        check(s1['stats']['rows'] == 1, '2027-01 命中 2026-12-26（跨年正确）',
              s1['stats']['rows'])
    except Exception as e:
        check(False, '迁移测试执行失败：%s' % e)
    finally:
        config.DB_PATH = old_path
        db._local = _th.local()           # 还原，避免污染后续
        try:
            db.init_db()
        except Exception:
            pass


def _check_server_source():
    """server.py 源码体检（踩过的两个坑）"""
    with open(os.path.join(BASE, 'server.py'), encoding='utf-8') as f:
        src = f.read()

    # 坑1：banner(srv) 被调用了两次，启动横幅打印两遍
    n = len(re.findall(r'^\s*banner\(srv\)\s*$', src, re.M))
    check(n == 1, '启动横幅只打印一次（banner 调用 %d 次）' % n)

    # 坑2：端口回退后仍用 config.PORT 打开浏览器，导致打开打不开的地址
    m = re.search(r'webbrowser\.open\((.{0,120})', src, re.S)
    check(bool(m) and 'used_port' in m.group(1),
          '浏览器用实际监听端口 used_port，而非 config.PORT')


def _check_fill_window(tokens, admin, pids):
    """「下周填本周」：周期没结束不允许填。

    这条断言不依赖运行当天的具体日期——都从 today 现算。
    """
    from datetime import date as _date

    from app import datex

    today = _date.today()
    cur_ps, cur_pe = datex.period_of_date(today)
    last_ps, last_pe = datex.fillable_period(today)
    nxt_ps, nxt_pe = datex.next_period(cur_pe)

    # 关闭了时间窗的这批断言在上面已经通过；这里重新打开
    config.FILL_REQUIRE_PERIOD_ENDED = True
    try:
        # --- 1. 最近一个已结束的周期 -----------------------------
        check(last_pe < today, '「该填的一期」结束日 %s 早于今天 %s'
              % (last_pe, today), (last_ps, last_pe))
        code, r = call('GET', '/api/period?periodStart=' + last_ps.isoformat(),
                       token=tokens['lina'])
        check(code == 200 and r['data']['editable'] is True,
              '已结束的周期可编辑', r['data'].get('editable'))

        # --- 2. 不指定周期时默认落到「该填的一期」 ---------------
        code, r = call('GET', '/api/period', token=tokens['lina'])
        check(code == 200 and r['data']['periodStart'] == last_ps.isoformat(),
              '不传参数时默认打开最近已结束的周期（%s）' % last_ps,
              r['data'].get('periodStart'))

        # --- 3. 当前周期（今天所在的）应锁定 ---------------------
        # 注意：第 9 节的 copy-prev 已经把 lina 的 10-26 那期填过了，
        # 这里换一个没有该周期记录的账号，才能验证"预填"行为本身。
        probe = tokens['zhaomin']
        code, r = call('GET', '/api/period?periodStart=' + cur_ps.isoformat(),
                       token=probe)
        check(code == 200 and r['data']['editable'] is False,
              '今天所在的周期（%s ~ %s）为只读' % (cur_ps, cur_pe),
              r['data'].get('editable'))
        check('还没结束' in (r['data'].get('lockReason') or ''),
              '锁定原因说明是"还没结束"', r['data'].get('lockReason'))

        # 未来的非工作日不能被预填成「休假」
        fut = [x for x in r['data']['days']
               if datex.parse_ymd(x['date']) > today and not x['isWorkday']]
        bad_fut = [(x['date'], x['weekday'], x['items'][0].get('work_type'),
                    x['items'][0].get('hours'), len(x['items'])) for x in fut
                   if x['items'][0].get('work_type')]
        check(fut and not bad_fut,
              '未来 %d 个休息日没有被预填成休假' % len(fut), bad_fut)
        # 已经过去的休息日仍然要预填「休假」，方便直接提交
        past_off = [x for x in r['data']['days']
                    if datex.parse_ymd(x['date']) <= today and not x['isWorkday']]
        check(all(x['items'][0].get('work_type') == '休假' for x in past_off),
              '已过去的 %d 个休息日照常预填休假' % len(past_off),
              [(x['date'], x['items'][0].get('work_type')) for x in past_off])

        # --- 4. 成员保存未结束的周期 → 拒绝 ---------------------
        its = build_items(r['data']['days'], pids, rd_hours=8, seed=1)
        code, r2 = call('POST', '/api/period/save',
                        {'periodStart': cur_ps.isoformat(), 'items': its},
                        tokens['lina'])
        check(code == 422, '成员保存未结束的周期被拒绝（HTTP %s）' % code)
        check(isinstance(r2, dict) and r2.get('code') == 'PERIOD_LOCKED',
              '错误码为 PERIOD_LOCKED', r2.get('code') if isinstance(r2, dict) else r2)
        check(isinstance(r2, dict) and '还没结束' in (r2.get('message') or ''),
              '提示语说明本期还没结束',
              r2.get('message') if isinstance(r2, dict) else '')

        # 提交 / 复制 同样被挡住
        code, _ = call('POST', '/api/period/submit',
                       {'periodStart': cur_ps.isoformat()}, tokens['lina'])
        check(code == 422, '提交未结束的周期被拒绝')
        code, _ = call('POST', '/api/period/copy-prev',
                       {'periodStart': cur_ps.isoformat()}, tokens['lina'])
        check(code == 422, '复制到未结束的周期被拒绝')

        # --- 5. 更远的未来周期 → 拒绝（提示"还没开始"）----------
        code, r3 = call('POST', '/api/period/save',
                        {'periodStart': nxt_ps.isoformat(),
                         'items': build_items(
                             call('GET', '/api/period?periodStart=' + nxt_ps.isoformat(),
                                  token=admin)[1]['data']['days'],
                             pids, rd_hours=8, seed=2)},
                        tokens['lina'])
        check(code == 422, '填下一期也被拒绝')
        check(isinstance(r3, dict) and '还没开始' in (r3.get('message') or ''),
              '提示语说明本期还没开始',
              r3.get('message') if isinstance(r3, dict) else '')

        # --- 6. 管理员的破例权限 --------------------------------
        code, radm = call('GET', '/api/period?periodStart=' + cur_ps.isoformat(),
                          token=admin)
        check(code == 200 and radm['data']['editable'] is True,
              '管理员看未结束的周期也可编辑（补录用）',
              radm['data'].get('editable'))
        its2 = build_items(radm['data']['days'], pids, rd_hours=8, seed=3)
        code, r4 = call('POST', '/api/period/save',
                        {'periodStart': cur_ps.isoformat(), 'items': its2}, admin)
        check(code == 200, '管理员可补录未结束的周期', r4)

        # --- 7. my_status 也带可填状态与「该填的一期」-----------
        code, r5 = call('GET', '/api/my-status?month=' + MONTH, token=tokens['lina'])
        st = r5['data']
        check(st.get('fillablePeriodStart') == last_ps.isoformat(),
              '月度页给出「现在该填的一期」', st.get('fillablePeriodStart'))
        check(all('editable' in p for p in st['periods']),
              '月度页每个周期都带可填状态')

        # --- 8. 关掉开关后恢复自由填报 --------------------------
        config.FILL_REQUIRE_PERIOD_ENDED = False
        code, _ = call('POST', '/api/period/save',
                       {'periodStart': cur_ps.isoformat(),
                        'items': build_items(radm['data']['days'], pids,
                                             rd_hours=8, seed=4)},
                       tokens['lina'])
        check(code == 200, '把 FILL_REQUIRE_PERIOD_ENDED 关掉后不再限制')
    finally:
        config.FILL_REQUIRE_PERIOD_ENDED = False   # 还原，避免影响后续小节


def _check_bats():
    """所有 .bat 必须是纯 ASCII。

    cmd.exe 在 chcp 65001 下解析含中文的 .bat 会错位，导致
    「不是内部或外部命令」，窗口一闪而过 —— 这正是实际踩过的坑。
    """
    root = BASE
    bad = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ('data', '输出', '备份', 'vendor', '__pycache__')]
        for fn in filenames:
            if not fn.lower().endswith('.bat'):
                continue
            p = os.path.join(dirpath, fn)
            total += 1
            with open(p, 'rb') as f:
                raw = f.read()
            n = sum(1 for b in raw if b > 127)
            if n:
                bad.append('%s（%d 个非 ASCII 字节）' % (fn, n))
    check(total >= 6, '找到 %d 个 .bat 启动脚本' % total)
    check(not bad, '全部 .bat 均为纯 ASCII' + ('' if not bad else '，仍超标：' + '；'.join(bad)))

    # 中文名启动入口应转调英文名入口，避免中文路径/文件名引发解析问题
    alias = os.path.join(root, '启动服务.bat')
    if os.path.exists(alias):
        with open(alias, 'rb') as f:
            txt = f.read().decode('ascii', 'replace').lower()
        check('start_server.bat' in txt, '启动服务.bat 转调 start_server.bat')
    check(os.path.exists(os.path.join(root, 'start_server.bat')),
          '英文入口 start_server.bat 存在')

    # 安装包自带便携运行时；能自己干活的脚本要优先用它，否则目标机没装 Python 就跑不起来
    for name in ('start_server.bat', '停止服务.bat'):
        p = os.path.join(root, name)
        if not os.path.exists(p):
            check(False, '%s 存在' % name)
            continue
        with open(p, 'rb') as f:
            txt = f.read().decode('ascii', 'replace').lower()
        check('runtime\\python.exe' in txt, '%s 优先使用自带 runtime' % name)

    # 卸载入口
    un = os.path.join(root, '卸载.bat')
    check(os.path.exists(un), '卸载.bat 存在')
    if os.path.exists(un):
        with open(un, 'rb') as f:
            txt = f.read().decode('ascii', 'replace').lower()
        check('uninstall.py' in txt, '卸载.bat 调用 uninstall.py')
    check(os.path.exists(os.path.join(root, 'uninstall.py')), 'uninstall.py 存在')


def _check_stop_script():
    """stop.py 只能识别「监听」本端口的进程。

    踩过的坑：把 TCP 连接行（对端端口 8000 的 TIME_WAIT）当成服务进程，
    结果去 kill PID 0，报「拒绝访问」。
    """
    import stop

    _cwd = os.getcwd()
    fake = (
        '  协议  本地地址           外部地址          状态           PID\n'
        '  TCP    0.0.0.0:8000        0.0.0.0:0        LISTENING       5744\n'
        '  TCP    127.0.0.1:57161     127.0.0.1:8000   TIME_WAIT       0\n'
        '  TCP    172.17.12.133:8000  172.17.12.5:50   ESTABLISHED     5744\n'
        '  TCP    [::]:8000           [::]:0           LISTENING       5744\n'
        '  TCP    0.0.0.0:135         0.0.0.0:0        LISTENING       900\n'
    )
    orig = stop._run
    try:
        stop._run = lambda cmd: (0, fake)
        pids = stop.find_pids_on_port(8000)
        check(pids == [5744], 'stop.py 只挑出监听进程并去重（%r）' % (pids,))
        check(stop.find_pids_on_port(8080) == [], 'stop.py 不会误判其他端口')

        stop._run = lambda cmd: (0, '')
        check(stop.find_pids_on_port(8000) == [], 'stop.py 空输出时视为无服务')

        stop._run = lambda cmd: (0, 'SUCCESS')
        check(stop.kill_pid(5744)[0] is True, 'stop.py 结束成功时返回成功')
        stop._run = lambda cmd: (128, 'ERROR: The process "9" not found.')
        ok, note = stop.kill_pid(9)
        check(ok is True and '自行退出' in note, 'stop.py 进程已退出时视为已停止')
        stop._run = lambda cmd: (5, 'ERROR: Access denied')
        ok, note = stop.kill_pid(5744)
        check(ok is False and 'denied' in note, 'stop.py 无权限时保留原始原因')
    finally:
        stop._run = orig
        os.chdir(_cwd)  # stop.py 导入时会 chdir(BASE)，这里还原


def _check_launcher_importable():
    """launcher / diagnose / backup 必须可导入（语法与依赖无误）"""
    import importlib
    for name in ('launcher', 'diagnose', 'backup', 'stop'):
        try:
            mod = importlib.import_module(name)
            importlib.reload(mod)
            check(True, '%s.py 可正常加载' % name)
        except Exception as e:
            check(False, '%s.py 加载失败：%s' % (name, e))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAIL += 1
        FAILED.append('异常：%s' % e)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        print('\n' + '=' * 54)
        print('  结果：%d 通过 / %d 失败' % (PASS, FAIL))
        for n in FAILED:
            print('    - %s' % n)
        print('=' * 54)
        sys.exit(1 if FAIL else 0)
