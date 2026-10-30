# -*- coding: utf-8 -*-
"""Excel 报表生成（openpyxl）
- 月度工时统计表（工时明细 / 人员汇总 / 项目汇总）
- 原始工时记录导出（留底用）
- 个人年度台账
"""
import os
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import config, datex, service
from .errors import not_found

FONT_NAME = config.REPORT_FONT
HEADER_FONT = Font(name=FONT_NAME, size=config.REPORT_HEADER_SIZE, bold=True, color='FF1F2329')
BODY_FONT = Font(name=FONT_NAME, size=config.REPORT_BODY_SIZE, color='FF1F2329')
TOTAL_FONT = Font(name=FONT_NAME, size=config.REPORT_BODY_SIZE, bold=True, color='FF1F2329')
TITLE_FONT = Font(name=FONT_NAME, size=14, bold=True, color='FF1F2329')
NOTE_FONT = Font(name=FONT_NAME, size=9, color='FF646A73')

HEADER_FILL = PatternFill('solid', fgColor='FFF2F3F5')
TOTAL_FILL = PatternFill('solid', fgColor='FFFAFAFA')
ZEBRA_FILL = PatternFill('solid', fgColor='FFFCFCFD')
SUB_FILL = PatternFill('solid', fgColor='FFEDF3FF')

_thin = Side(style='thin', color='FFD0D3D6')
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_total_top = Side(style='medium', color='FFB0B4B8')
TOTAL_BORDER = Border(left=_thin, right=_thin, top=_total_top, bottom=_thin)

CENTER = Alignment(horizontal='center', vertical='center')
LEFT = Alignment(horizontal='left', vertical='center')
LEFT_WRAP = Alignment(horizontal='left', vertical='center', wrap_text=True)
CENTER_WRAP = Alignment(horizontal='center', vertical='center', wrap_text=True)

DETAIL_HEADERS = config.DETAIL_HEADERS
DETAIL_WIDTHS = config.DETAIL_WIDTHS


# ================================================================ 通用样式
def _write_header(ws, headers, widths, row_no=1, height=26):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row_no, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.border = BORDER
        c.alignment = CENTER_WRAP
    ws.row_dimensions[row_no].height = height
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _style_row(ws, row_no, col_count, font=BODY_FONT, fill=None,
               alignment=CENTER, border=BORDER):
    for i in range(1, col_count + 1):
        c = ws.cell(row=row_no, column=i)
        c.font = font
        c.border = border
        c.alignment = alignment
        if fill is not None:
            c.fill = fill


def _title_row(ws, row_no, text, span):
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=span)
    c = ws.cell(row=row_no, column=1, value=text)
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[row_no].height = 30


# ================================================================ 月度统计表
def make_month_workbook(data):
    wb = Workbook()

    # -------------------------------------------------- Sheet1 工时明细
    ws1 = wb.active
    ws1.title = '工时明细'
    ws1.freeze_panes = 'A2'
    widths = list(DETAIL_WIDTHS) + list(getattr(config, 'DETAIL_WIDTHS_EXTRA', [10, 12]))
    _write_header(ws1, DETAIL_HEADERS, widths, 1)
    ncol = len(DETAIL_HEADERS)

    # 按「日期+姓名」累计当日合计工时（同一天多条明细时最后一条显示合计）
    day_total = {}
    for d in data['detail']:
        kk = (d['date'], d['name'])
        day_total[kk] = day_total.get(kk, 0) + (d.get('hours') or 0)
    seen_day = {}

    for idx, d in enumerate(data['detail']):
        r = idx + 2
        kk = (d['date'], d['name'])
        seen_day[kk] = seen_day.get(kk, 0) + 1
        is_last_of_day = seen_day[kk] >= sum(
            1 for x in data['detail'] if (x['date'], x['name']) == kk)

        ws1.cell(row=r, column=1, value=datex.parse_ymd(d['date']))
        ws1.cell(row=r, column=2, value=d['name'])
        ws1.cell(row=r, column=3, value=d['jobTitle'] or config.EMPTY_MARK)
        ws1.cell(row=r, column=4, value=d['projectCode'] or config.EMPTY_MARK)
        ws1.cell(row=r, column=5, value=d['projectName'] or config.EMPTY_MARK)
        ws1.cell(row=r, column=6, value=d['rdHours'])
        ws1.cell(row=r, column=7, value=d['nrdHours'])
        ws1.cell(row=r, column=8, value=d['content'])
        ws1.cell(row=r, column=9, value=d.get('workType') or config.EMPTY_MARK)
        ws1.cell(row=r, column=10,
                 value=(day_total[kk] if is_last_of_day else ''))

        _style_row(ws1, r, ncol, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws1.cell(row=r, column=1).number_format = 'yyyy-mm-dd'
        ws1.cell(row=r, column=6).number_format = '0.##'
        ws1.cell(row=r, column=7).number_format = '0.##'
        ws1.cell(row=r, column=8).alignment = LEFT_WRAP
        ws1.cell(row=r, column=10).number_format = '0.##'
        ws1.row_dimensions[r].height = 20

    tr = len(data['detail']) + 2
    bd = data['breakdown']
    ws1.cell(row=tr, column=1, value='合计')
    ws1.cell(row=tr, column=6, value=bd['rdHours'])
    ws1.cell(row=tr, column=7, value=bd['nrdHours'])
    ws1.cell(row=tr, column=8,
             value='共 %d 条 / %d 人：研发 %g 小时 / 非研发 %g 小时 / 合计 %g 小时'
                   % (data['stats']['rows'], data['stats']['headcount'],
                      bd['rdHours'], bd['nrdHours'], bd['totalHours']))
    ws1.cell(row=tr, column=9, value=config.EMPTY_MARK)
    ws1.cell(row=tr, column=10, value=bd['totalHours'])
    _style_row(ws1, tr, ncol, font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
    ws1.cell(row=tr, column=8).alignment = LEFT_WRAP
    ws1.cell(row=tr, column=6).number_format = '0.##'
    ws1.cell(row=tr, column=7).number_format = '0.##'
    ws1.cell(row=tr, column=10).number_format = '0.##'
    ws1.row_dimensions[tr].height = 22

    if data['detail']:
        ws1.auto_filter.ref = 'A1:%s1' % chr(64 + ncol)

    # -------------------------------------------------- Sheet2 人员汇总
    ws2 = wb.create_sheet('人员汇总')
    ws2.freeze_panes = 'A3'
    _title_row(ws2, 1, '%s研发工时统计表 · 人员汇总'
               % (data.get('monthFullLabel') or data['monthLabel']), 10)

    h2 = ['姓名', '岗位', '研发工时', '非研发工时', '合计工时', '研发占比',
          '应出勤天数', '实填天数', '填写率']
    _write_header(ws2, h2, [12, 18, 12, 14, 12, 10, 12, 10, 10], 2)

    for idx, p in enumerate(data['perPerson']):
        r = idx + 3
        ws2.cell(row=r, column=1, value=p['name'])
        ws2.cell(row=r, column=2, value=p['jobTitle'] or config.EMPTY_MARK)
        ws2.cell(row=r, column=3, value=p['rd'])
        ws2.cell(row=r, column=4, value=p['nrd'])
        ws2.cell(row=r, column=5, value=p['total'])
        ws2.cell(row=r, column=6, value=(p['rdRatio'] or 0) / 100.0)
        ws2.cell(row=r, column=7, value=p['quotaDays'])
        ws2.cell(row=r, column=8, value=p['days'])
        ws2.cell(row=r, column=9, value=(p['rate'] or 0) / 100.0)
        ws2.cell(row=r, column=10, value=p.get('ot', 0))
        _style_row(ws2, r, 10, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws2.cell(row=r, column=6).number_format = '0.0%'
        ws2.cell(row=r, column=9).number_format = '0%'
        ws2.row_dimensions[r].height = 20

    st = data['stats']
    t2r = len(data['perPerson']) + 3
    ws2.cell(row=t2r, column=1, value='合计')
    ws2.cell(row=t2r, column=2, value='%d 人' % len(data['perPerson']))
    ws2.cell(row=t2r, column=3, value=bd['rdHours'])
    ws2.cell(row=t2r, column=4, value=bd['nrdHours'])
    ws2.cell(row=t2r, column=5, value=bd['totalHours'])
    ws2.cell(row=t2r, column=6, value=(bd['rdRatio'] or 0) / 100.0)
    ws2.cell(row=t2r, column=7, value=st['quotaDaysTotal'])
    ws2.cell(row=t2r, column=8, value=st['daysTotal'])
    ws2.cell(row=t2r, column=9, value=(st['fillRate'] or 0) / 100.0)
    _style_row(ws2, t2r, 9, font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
    ws2.cell(row=t2r, column=6).number_format = '0.0%'
    ws2.cell(row=t2r, column=9).number_format = '0%'
    ws2.row_dimensions[t2r].height = 22

    if data['perPerson']:
        ws2.auto_filter.ref = 'A2:J2'

    # -------------------------------------------------- Sheet3 项目汇总
    ws3 = wb.create_sheet('项目汇总')
    ws3.freeze_panes = 'A3'
    _title_row(ws3, 1, '%s研发工时统计表 · 项目汇总（研发费用归集口径）'
               % (data.get('monthFullLabel') or data['monthLabel']), 9)

    h3 = ['研发项目编号', '项目名称', '参与人数', '研发工时', '非研发工时',
          '总工时', '研发工时占比', '占全月工时比例', '工时人次']
    _write_header(ws3, h3, [16, 30, 10, 12, 12, 12, 12, 15, 10], 2)

    for idx, p in enumerate(data['perProject']):
        r = idx + 3
        ws3.cell(row=r, column=1, value=p['code'])
        ws3.cell(row=r, column=2, value=p['name'])
        ws3.cell(row=r, column=3, value=p['people'])
        ws3.cell(row=r, column=4, value=p['rd'])
        ws3.cell(row=r, column=5, value=p['nrd'])
        ws3.cell(row=r, column=6, value=p['total'])
        ws3.cell(row=r, column=7, value=(p['rdRatio'] or 0) / 100.0)
        ws3.cell(row=r, column=8, value=(p['ratioOfMonthTotal'] or 0) / 100.0)
        ws3.cell(row=r, column=9, value=p['times'])
        _style_row(ws3, r, 9, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws3.cell(row=r, column=2).alignment = LEFT_WRAP
        ws3.cell(row=r, column=7).number_format = '0.0%'
        ws3.cell(row=r, column=8).number_format = '0.0%'
        ws3.row_dimensions[r].height = 20

    # 合计行严格按"列"求和，不再混入全月口径（否则 G/H 两列会错位）
    t3r = len(data['perProject']) + 3
    tot_rd = sum(p['rd'] for p in data['perProject'])
    tot_nrd = sum(p['nrd'] for p in data['perProject'])
    tot_all = tot_rd + tot_nrd
    ws3.cell(row=t3r, column=1, value='合计')
    ws3.cell(row=t3r, column=2, value='%d 个项目' % st['projectCount'])
    ws3.cell(row=t3r, column=3, value=st.get('projectPeople') or '')
    ws3.cell(row=t3r, column=4, value=tot_rd)
    ws3.cell(row=t3r, column=5, value=tot_nrd)
    ws3.cell(row=t3r, column=6, value=tot_all)
    ws3.cell(row=t3r, column=7, value=(tot_rd / tot_all) if tot_all else 0)
    ws3.cell(row=t3r, column=8,
             value=(tot_rd / bd['totalHours']) if bd['totalHours'] else 0)
    ws3.cell(row=t3r, column=9, value=sum(p['times'] for p in data['perProject']))
    _style_row(ws3, t3r, 9, font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
    ws3.cell(row=t3r, column=7).number_format = '0.0%'
    ws3.cell(row=t3r, column=8).number_format = '0.0%'
    ws3.row_dimensions[t3r].height = 22

    if data['perProject']:
        ws3.auto_filter.ref = 'A2:I2'

    # ------------------- 工时构成（财务归集直接可用） -------------------
    base = t3r + 2
    _title_row(ws3, base, '工时构成（全月口径，供财务研发费用归集）', 9)
    sub_head = ['工时类别', '工时（小时）', '占全月总工时比例']
    for i, h in enumerate(sub_head, start=1):
        c = ws3.cell(row=base + 1, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.border = BORDER
        c.alignment = CENTER_WRAP
    ws3.row_dimensions[base + 1].height = 22

    sub_rows = [
        ('全月总工时', bd['totalHours'], 1.0),
        ('　其中：研发工时（已按项目归集，见上表）', bd['rdHours'], (bd['rdRatio'] or 0) / 100.0),
        ('　　　　非研发工时（不计入项目）', bd['nrdHours'], (bd['nrdRatio'] or 0) / 100.0),
    ]
    for i, (name, hours, ratio) in enumerate(sub_rows):
        r = base + 2 + i
        ws3.cell(row=r, column=1, value=name)
        ws3.cell(row=r, column=2, value=hours)
        ws3.cell(row=r, column=3, value=ratio)
        _style_row(ws3, r, 3, fill=SUB_FILL if i == 0 else None)
        ws3.cell(row=r, column=1).alignment = LEFT
        ws3.cell(row=r, column=2).number_format = '0.##'
        ws3.cell(row=r, column=3).number_format = '0.0%'
        ws3.row_dimensions[r].height = 20

    note_r = base + 5
    ws3.merge_cells(start_row=note_r, start_column=1, end_row=note_r, end_column=9)
    nc = ws3.cell(row=note_r, column=1,
                  value='说明：只有研发工时计入具体项目，非研发工时不计入任何项目；'
                        '「研发工时占比」= 本项目研发工时 ÷ 本项目总工时，'
                        '「占全月工时比例」= 本项目研发工时 ÷ 全月总工时（可直接作为研发费用归集比例）。'
                        '合计行为按列求和；全月口径（含非研发与休假）见上表「工时构成」。'
                        '本月休假 %g 个半天（0 工时，不计入任何项目）。'
                        % (st.get('leaveTotal', 0)))
    nc.font = NOTE_FONT
    nc.alignment = LEFT_WRAP
    ws3.row_dimensions[note_r].height = 34

    # -------------------------------------------------- Sheet4 填报周期
    rows = data.get('periodRows') or []
    if rows:
        ws4 = wb.create_sheet('填报周期')
        ws4.freeze_panes = 'A3'
        _title_row(ws4, 1, '%s 填报周期一览（跨周延伸的周期天数会大于 7 天）'
                   % (data.get('monthFullLabel') or data['monthLabel']), 7)
        _write_header(ws4, ['周期起', '周期止', '天数', '工作日', '覆盖人数', '条目数', '合计工时'],
                      [14, 14, 8, 8, 10, 10, 12], 2)
        for idx, p in enumerate(rows):
            r = idx + 3
            ws4.cell(row=r, column=1, value=datex.parse_ymd(p['periodStart']))
            ws4.cell(row=r, column=2, value=datex.parse_ymd(p['periodEnd']))
            ws4.cell(row=r, column=3, value=p['dayCount'])
            ws4.cell(row=r, column=4, value=p.get('workdays', ''))
            ws4.cell(row=r, column=5, value=p['people'])
            ws4.cell(row=r, column=6, value=p['filled'])
            ws4.cell(row=r, column=7, value=p.get('hours', ''))
            _style_row(ws4, r, 7, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
            ws4.cell(row=r, column=1).number_format = 'yyyy-mm-dd'
            ws4.cell(row=r, column=2).number_format = 'yyyy-mm-dd'
            ws4.cell(row=r, column=7).number_format = '0.##'
            ws4.row_dimensions[r].height = 20

    return wb


def month_period_rows(month, exclude_ids=None):
    """当月各填报周期的填报情况（跨月延伸的周期也能看出来）"""
    month = datex.normalize_month(month)
    excl = set()
    for x in (exclude_ids or []):
        try:
            excl.add(int(x))
        except (TypeError, ValueError):
            pass
    out = []
    for ps, pe in datex.periods_for_month(month):
        info = datex.period_info(ps, pe)
        filled, people, hours = db_count(ps, pe, excl)
        out.append({
            'periodStart': ps.isoformat(), 'periodEnd': pe.isoformat(),
            'dayCount': info['day_count'],
            'workdays': sum(1 for d in info['days'] if datex.is_workday(d)),
            'people': people, 'filled': filled, 'hours': round(hours, 1),
        })
    return out


def db_count(ps, pe, exclude_ids=None):
    from . import db
    excl = sorted(exclude_ids or [])
    sql = ('SELECT COUNT(*) AS c, COUNT(DISTINCT user_id) AS p,'
           ' COALESCE(SUM(rd_hours + nrd_hours),0) AS h FROM entries'
           ' WHERE work_date BETWEEN ? AND ?')
    args = [ps.isoformat(), pe.isoformat()]
    if excl:
        sql += ' AND user_id NOT IN (%s)' % ','.join('?' * len(excl))
        args += excl
    row = db.one(sql, tuple(args))
    if not row:
        return (0, 0, 0.0)
    return (row['c'], row['p'], float(row['h'] or 0))


def generate(month_str=None, data=None, exclude_ids=None):
    """生成月度报表文件，返回 (文件路径, 文件名, 汇总数据)"""
    data = data or service.month_summary(month_str, exclude_ids)
    if not data['detail']:
        raise not_found('%s没有任何工时记录，无法生成统计表' % data['monthLabel'])
    data['periodRows'] = month_period_rows(data['month'], exclude_ids)

    wb = make_month_workbook(data)
    fname = '%s研发工时统计表.xlsx' % data['monthLabel']
    path = os.path.join(config.OUTPUT_DIR, fname)
    wb.save(path)
    return path, fname, data


# ================================================================ 原始记录导出
RAW_HEADERS = [
    '序号', '填报周期起', '填报周期止', '日期', '星期', '当日第几条',
    '姓名', '账号', '岗位', '部门', '工时类型', '研发项目编号', '项目名称',
    '本次工时', '研发工时', '非研发工时', '具体工作内容', '状态', '填报时间',
]
RAW_WIDTHS = [6, 12, 12, 12, 7, 10, 10, 12, 16, 12, 9, 9, 15, 24, 10, 10, 12, 48, 8, 19]


def make_raw_workbook(data, title):
    wb = Workbook()

    ws1 = wb.active
    ws1.title = '原始记录'
    ws1.freeze_panes = 'A2'
    _write_header(ws1, RAW_HEADERS, RAW_WIDTHS, 1)

    for idx, r in enumerate(data['rows']):
        row = idx + 2
        vals = [
            r['seq'], r['periodStart'], r['periodEnd'], r['date'], r['weekday'],
            r.get('daySeq', 1), r['name'], r['account'], r['jobTitle'], r['dept'],
            r['workType'], r['projectCode'], r['projectName'],
            r.get('hours', 0), r['rdHours'], r['nrdHours'], r['content'],
            r['status'], r['updatedAt'],
        ]
        for ci, v in enumerate(vals, start=1):
            ws1.cell(row=row, column=ci, value=v)
        _style_row(ws1, row, len(RAW_HEADERS), fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws1.cell(row=row, column=1).number_format = '0'
        for _c in (15, 16, 17):
            ws1.cell(row=row, column=_c).number_format = '0.##'
        ws1.cell(row=row, column=18).alignment = LEFT_WRAP
        ws1.row_dimensions[row].height = 18

    tr = len(data['rows']) + 2
    rd = sum(r['rdHours'] for r in data['rows'])
    nrd = sum(r['nrdHours'] for r in data['rows'])
    tot_hours = sum(r.get('hours', 0) for r in data['rows'])
    ws1.cell(row=tr, column=1, value='合计')
    ws1.cell(row=tr, column=15, value=tot_hours)
    ws1.cell(row=tr, column=16, value=rd)
    ws1.cell(row=tr, column=17, value=nrd)
    ws1.cell(row=tr, column=18,
             value='共 %d 条：合计 %g 小时（研发 %g / 非研发 %g）'
                   % (data['count'], tot_hours, rd, nrd))
    _style_row(ws1, tr, len(RAW_HEADERS), font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
    ws1.cell(row=tr, column=18).alignment = LEFT_WRAP
    for _c in (15, 16, 17):
        ws1.cell(row=tr, column=_c).number_format = '0.##'
    ws1.row_dimensions[tr].height = 22
    if data['rows']:
        ws1.auto_filter.ref = 'A1:T1'

    # 按人汇总
    ws2 = wb.create_sheet('按人汇总')
    _title_row(ws2, 1, '%s · 按人汇总' % title, 5)
    _write_header(ws2, ['姓名', '研发工时', '非研发工时', '合计工时', '半天数'],
                  [14, 12, 14, 12, 10], 2)
    for idx, p in enumerate(data['byPerson']):
        r = idx + 3
        ws2.cell(row=r, column=1, value=p['name'])
        ws2.cell(row=r, column=2, value=p['rd'])
        ws2.cell(row=r, column=3, value=p['nrd'])
        ws2.cell(row=r, column=4, value=p['rd'] + p['nrd'])
        ws2.cell(row=r, column=5, value=p['units'])
        _style_row(ws2, r, 5, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws2.row_dimensions[r].height = 20

    # 按周期汇总
    ws3 = wb.create_sheet('按周期汇总')
    _title_row(ws3, 1, '%s · 按填报周期汇总' % title, 6)
    _write_header(ws3, ['周期起', '周期止', '研发工时', '非研发工时', '合计工时', '半天数'],
                  [14, 14, 12, 14, 12, 10], 2)
    for idx, p in enumerate(data['byPeriod']):
        r = idx + 3
        ws3.cell(row=r, column=1, value=p['periodStart'])
        ws3.cell(row=r, column=2, value=p['periodEnd'])
        ws3.cell(row=r, column=3, value=p['rd'])
        ws3.cell(row=r, column=4, value=p['nrd'])
        ws3.cell(row=r, column=5, value=p['rd'] + p['nrd'])
        ws3.cell(row=r, column=6, value=p['units'])
        _style_row(ws3, r, 6, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws3.row_dimensions[r].height = 20

    return wb


def raw_export_name(params):
    if params.get('period') or params.get('periodStart'):
        ps, pe = service._resolve_period(params.get('period') or params.get('periodStart'))
        return '原始工时记录_%s至%s.xlsx' % (ps.isoformat(), pe.isoformat())
    if params.get('month'):
        ym = datex.normalize_month(params['month'])
        return '原始工时记录_%s.xlsx' % ym
    d_from = params.get('from') or ''
    d_to = params.get('to') or ''
    if d_from or d_to:
        return '原始工时记录_%s至%s.xlsx' % (d_from or '最早', d_to or '最新')
    return '原始工时记录_全部.xlsx'


def generate_raw(params):
    data = service.export_rows(params)
    if not data['count']:
        raise not_found('所选范围内没有工时记录')
    fname = raw_export_name(params)
    title = fname.replace('.xlsx', '')
    wb = make_raw_workbook(data, title)
    path = os.path.join(config.OUTPUT_DIR, fname)
    wb.save(path)
    return path, fname, data


def generate_raw_csv(params):
    import csv
    import io as _io
    data = service.export_rows(params)
    if not data['count']:
        raise not_found('所选范围内没有工时记录')
    fname = raw_export_name(params).replace('.xlsx', '.csv')
    buf = _io.StringIO()
    buf.write('\ufeff')  # BOM，让 Excel 直接认出 UTF-8
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(RAW_HEADERS)
    for r in data['rows']:
        w.writerow([
            r['seq'], r['periodStart'], r['periodEnd'], r['date'], r['weekday'],
            r.get('daySeq', 1), r['name'], r['account'], r['jobTitle'], r['dept'],
            r['workType'], r.get('kind', '正常'), r['projectCode'], r['projectName'],
            r.get('hours', 0), r['rdHours'], r['nrdHours'], r['content'],
            r['status'], r['updatedAt'],
        ])
    path = os.path.join(config.OUTPUT_DIR, fname)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(buf.getvalue())
    return path, fname, data


# ================================================================ 年度台账
def make_year_workbook(ledger):
    wb = Workbook()

    if ledger.get('mode') == 'overview':
        ws = wb.active
        ws.title = '全员年度汇总'
        ws.freeze_panes = 'A3'
        _title_row(ws, 1, '%d 年度工时台账 · 全员汇总' % ledger['year'], 10)
        heads = ['姓名', '岗位', '部门', '研发工时', '非研发工时', '合计工时',
                 '研发占比', '应出勤天数', '实填天数', '填写率']
        _write_header(ws, heads, [12, 18, 14, 12, 14, 12, 10, 12, 10, 10], 2)
        for idx, p in enumerate(ledger['rows']):
            r = idx + 3
            vals = [p['name'], p['jobTitle'] or config.EMPTY_MARK, p['dept'] or config.EMPTY_MARK,
                    p['rd'], p['nrd'], p['total'], (p['rdRatio'] or 0) / 100.0,
                    p.get('workdays', 0), p.get('days', 0), (p['rate'] or 0) / 100.0]
            for ci, v in enumerate(vals, start=1):
                ws.cell(row=r, column=ci, value=v)
            _style_row(ws, r, 10, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
            ws.cell(row=r, column=7).number_format = '0.0%'
            ws.cell(row=r, column=10).number_format = '0%'
            ws.row_dimensions[r].height = 20

        t = ledger['totals']
        tr = len(ledger['rows']) + 3
        vals = ['合计', '%d 人' % len(ledger['rows']), '', t['rd'], t['nrd'], t['total'],
                (t['rdRatio'] or 0) / 100.0, t.get('workdays', 0), t.get('days', 0),
                (t['rate'] / 100.0) if t['rate'] else 0]
        for ci, v in enumerate(vals, start=1):
            ws.cell(row=tr, column=ci, value=v)
        _style_row(ws, tr, 10, font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
        ws.cell(row=tr, column=7).number_format = '0.0%'
        ws.cell(row=tr, column=10).number_format = '0%'
        ws.row_dimensions[tr].height = 22
        if ledger['rows']:
            ws.auto_filter.ref = 'A2:J2'
        return wb

    # ---------------- 个人台账 ----------------
    ws = wb.active
    ws.title = '个人年度台账'
    ws.freeze_panes = 'A2'
    _write_header(ws, ['月份', '研发工时', '非研发工时', '合计工时', '研发占比',
                       '应出勤天数', '实填天数', '填写率'],
                  [10, 12, 14, 12, 10, 12, 10, 10], 1)

    for idx, m in enumerate(ledger['months']):
        r = idx + 2
        vals = [m['month'], m['rd'], m['nrd'], m['total'],
                (m['rdRatio'] or 0) / 100.0, m.get('workdays', 0), m.get('days', 0),
                (m['rate'] or 0) / 100.0]
        for ci, v in enumerate(vals, start=1):
            ws.cell(row=r, column=ci, value=v)
        _style_row(ws, r, 8, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws.cell(row=r, column=5).number_format = '0.0%'
        ws.cell(row=r, column=8).number_format = '0%'
        ws.row_dimensions[r].height = 20

    t = ledger['totals']
    tr = len(ledger['months']) + 2
    vals = ['全年合计', t['rd'], t['nrd'], t['total'], (t['rdRatio'] or 0) / 100.0,
            t.get('workdays', 0), t.get('days', 0), (t['rate'] or 0) / 100.0]
    for ci, v in enumerate(vals, start=1):
        ws.cell(row=tr, column=ci, value=v)
    _style_row(ws, tr, 8, font=TOTAL_FONT, fill=TOTAL_FILL, border=TOTAL_BORDER)
    ws.cell(row=tr, column=5).number_format = '0.0%'
    ws.cell(row=tr, column=8).number_format = '0%'
    ws.row_dimensions[tr].height = 22

    ws.cell(row=tr + 2, column=1, value='姓名：%s　岗位：%s　部门：%s　年度：%d'
            % (ledger['name'], ledger['jobTitle'] or config.EMPTY_MARK,
               ledger['dept'] or config.EMPTY_MARK, ledger['year'])).font = NOTE_FONT
    ws.merge_cells(start_row=tr + 2, start_column=1, end_row=tr + 2, end_column=8)

    # 项目分布
    ws2 = wb.create_sheet('年度项目分布')
    _title_row(ws2, 1, '%d 年度研发项目工时分布 · %s' % (ledger['year'], ledger['name']), 5)
    _write_header(ws2, ['研发项目编号', '项目名称', '研发工时', '占个人年度研发比例', '涉及月份数'],
                  [16, 30, 12, 20, 12], 2)
    for idx, p in enumerate(ledger['projects']):
        r = idx + 3
        ws2.cell(row=r, column=1, value=p['code'])
        ws2.cell(row=r, column=2, value=p['name'])
        ws2.cell(row=r, column=3, value=p['rd'])
        ws2.cell(row=r, column=4, value=(p['ratio'] or 0) / 100.0)
        ws2.cell(row=r, column=5, value=p['monthCount'])
        _style_row(ws2, r, 5, fill=(ZEBRA_FILL if idx % 2 == 1 else None))
        ws2.cell(row=r, column=2).alignment = LEFT_WRAP
        ws2.cell(row=r, column=4).number_format = '0.0%'
        ws2.row_dimensions[r].height = 20

    return wb


def generate_year(ledger):
    if ledger.get('mode') == 'overview':
        fname = '%d年度工时台账_全员.xlsx' % ledger['year']
    else:
        fname = '%d年度工时台账_%s.xlsx' % (ledger['year'], ledger['name'])
    wb = make_year_workbook(ledger)
    path = os.path.join(config.OUTPUT_DIR, fname)
    wb.save(path)
    return path, fname, ledger
