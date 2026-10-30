/* 研发工时统计系统 —— 前端（原生 JS，无构建、无外部依赖） */
(function () {
  'use strict';

  var TOKEN_KEY = 'ts_token';
  var S = {
    user: null,
    token: localStorage.getItem(TOKEN_KEY) || '',
    view: '',
    period: null,
    periodStart: '',
    month: '',
    year: new Date().getFullYear(),
    yearUser: '',        // 管理员看某人时用
    projects: [],
    settings: null,
    exportMode: 'month',
    exportFormat: 'xlsx'
  };

  /* ============================ 工具 ============================ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function fmtDate(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function addDays(d, n) { var x = new Date(d.getTime()); x.setDate(x.getDate() + n); return x; }
  function parseYmd(s) { var p = String(s).split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function thisMonday() { var d = new Date(); return addDays(d, -((d.getDay() + 6) % 7)); }

  /* 工资月口径：默认「上月26日 ~ 当月25日」由服务端下发，取不到时按 26 处理 */
  var CYCLE = { startDay: 26 };
  function cycleStartDay() { return CYCLE.startDay || 1; }
  /* 任意日期(date 或 'YYYY-MM-DD') -> 所属工资月 'YYYY-MM' */
  function payMonth(d) {
    if (typeof d === 'string') d = parseYmd(d);
    d = d || new Date();
    var day = cycleStartDay();
    var y = d.getFullYear(), m = d.getMonth() + 1;
    if (day > 1 && d.getDate() >= day) {
      if (m === 12) { y += 1; m = 1; } else { m += 1; }
    }
    return y + '-' + pad(m);
  }
  function thisMonth() { return payMonth(new Date()); }
  /* 'YYYY-MM' -> 口径说明，如「5月26日 - 6月25日」 */
  function monthRangeText(ym) {
    var day = cycleStartDay();
    var p = String(ym || thisMonth()).split('-');
    var y = +p[0], m = +p[1];
    if (!y || !m) return '';
    if (day <= 1) {
      var last = new Date(y, m, 0).getDate();
      return m + '月1日 - ' + m + '月' + last + '日';
    }
    var pm = m === 1 ? 12 : m - 1, py = m === 1 ? y - 1 : y;
    var head = (py !== y) ? (py + '年' + pm + '月' + day + '日') : (pm + '月' + day + '日');
    return head + ' - ' + m + '月' + (day - 1) + '日';
  }
  function todayStr() { return fmtDate(new Date()); }

  function toast(msg, type) {
    var box = $('#toast');
    var t = document.createElement('div');
    t.className = 'toast' + (type ? ' ' + type : '');
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(function () {
      t.style.opacity = '0'; t.style.transition = 'opacity .3s';
      setTimeout(function () { t.remove(); }, 320);
    }, type === 'err' ? 4200 : 2400);
  }

  function stat(k, v) {
    return '<div class="stat"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>';
  }

  /**
   * 长文本单元格（项目名称等）：限定宽度内自动换行，**不截断数据**，
   * 悬停用 title 显示完整内容，避免超长项目名把表格撑爆。
   * @param text 原始文本
   * @param extra 附加 HTML（如状态标签）
   * @param cls   额外的样式类（narrow = 更窄）
   */
  function nameCell(text, extra, cls) {
    var t = String(text == null ? '' : text);
    return '<td class="left name-cell' + (cls ? ' ' + cls : '') + '" title="' + esc(t) + '">' +
      esc(t) + (extra || '') + '</td>';
  }

  /* ============================ 请求 ============================ */
  function api(path, opts) {
    opts = opts || {};
    var headers = { 'X-Token': S.token };
    var body = opts.body;
    if (body !== undefined && !(body instanceof Blob) && !(body instanceof File)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    return fetch(path, {
      method: opts.method || (body !== undefined ? 'POST' : 'GET'),
      headers: headers,
      body: body,
      credentials: 'same-origin'
    }).then(function (r) {
      var ct = r.headers.get('Content-Type') || '';
      if (ct.indexOf('application/json') < 0) {
        return { _blob: true };
      }
      return r.json().then(function (j) {
        if (j && j.code === 'UNAUTHORIZED') { logoutLocal(); throw new Error(j.message || '请重新登录'); }
        if (j && j.ok === false) {
          var e = new Error(j.message || '请求失败');
          e.code = j.code; e.details = j.details; throw e;
        }
        return j || {};
      });
    });
  }

  /* ============================ 弹窗 ============================ */
  /**
   * opt.lockable = true 时，右上角显示「锁定」开关。
   * 锁定后：点遮罩、按 Esc 都不会关闭，只有点「取消」「确定」或解锁后才关，
   * 避免填了半天被误点作废。
   */
  function modal(opt) {
    var host = $('#modalHost');
    var canLock = !!opt.lockable;
    host.innerHTML =
      '<div class="modal-mask"><div class="modal">' +
        '<div class="modal-head">' + esc(opt.title || '') +
          (canLock
            ? '<button type="button" class="modal-lock" id="mdlLock" title="锁定后点空白处不会关闭">' +
              '🔓 未锁定</button>'
            : '') +
        '</div>' +
        '<div class="modal-body">' + (opt.body || '') + '</div>' +
        '<div class="modal-foot">' +
          '<button class="btn" data-mc>取消</button>' +
          '<button class="btn primary" data-mok>' + esc(opt.okText || '确定') + '</button>' +
        '</div>' +
      '</div></div>';
    var mask = $('.modal-mask', host);
    var locked = !!opt.defaultLocked;
    var dirty = false;

    function syncLockBtn() {
      var b = $('#mdlLock', host);
      if (!b) return;
      b.className = 'modal-lock' + (locked ? ' on' : '');
      b.textContent = locked ? '🔒 已锁定' : '🔓 未锁定';
    }

    function close(force) {
      if (!force && locked) {
        toast('已锁定，点「取消」或「确定」才能关闭', 'err');
        return;
      }
      document.removeEventListener('keydown', onKey);
      host.innerHTML = '';
    }

    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      }
    }

    $('[data-mc]', host).onclick = function () { close(true); };

    // 点遮罩：锁定 / 已输入内容时都要先确认，不能一点就没了
    mask.onclick = function (e) {
      if (e.target !== mask) return;
      if (locked) { toast('已锁定，点「取消」或「确定」才能关闭', 'err'); return; }
      if (dirty) {
        if (!window.confirm('已经填了内容，确定放弃并关闭吗？')) return;
      }
      close(true);
    };

    if (canLock) {
      var lb = $('#mdlLock', host);
      lb.onclick = function (e) {
        e.stopPropagation();
        locked = !locked;
        syncLockBtn();
        if (locked) toast('已锁定：点空白处不会再关闭', 'ok');
      };
      syncLockBtn();
    }

    // 记录是否有输入，用于放弃前的二次确认
    host.addEventListener('input', function (e) {
      if (e.target && e.target.matches && e.target.matches('input,textarea,select')) dirty = true;
    });

    document.addEventListener('keydown', onKey);

    $('[data-mok]', host).onclick = function () {
      var ok = opt.onOk ? opt.onOk(host) : true;
      if (ok !== false) { locked = false; close(true); }
    };
    if (opt.onMount) opt.onMount(host);
    return { close: function () { close(true); }, isDirty: function () { return dirty; } };
  }

  /* ============================ 登录 ============================ */
  function logoutLocal() {
    S.token = ''; S.user = null;
    localStorage.removeItem(TOKEN_KEY);
    $('#app').classList.add('hidden');
    $('#login').classList.remove('hidden');
  }

  function doLogin(username, password) {
    return api('/api/login', { method: 'POST', body: { username: username, password: password } })
      .then(function (j) {
        S.token = j.token; S.user = j.user;
        localStorage.setItem(TOKEN_KEY, j.token);
        return j;
      });
  }

  function enterApp() {
    $('#login').classList.add('hidden');
    $('#app').classList.remove('hidden');
    var u = S.user || {};
    $('#hdrUser').textContent = (u.name || u.username) + (u.isAdmin ? ' · 管理员' : '');
    $('#hdrAvatar').textContent = (u.name || '?').slice(-1);
    buildTabs();
    if (S.user.mustChangePwd) {
      toast('请先修改初始密码', 'err');
      switchView('settings');
    } else {
      switchView('fill');
    }
  }

  /* ============================ 标签页 ============================ */
  var VIEWS = [
    { key: 'fill', name: '我的工时' },
    { key: 'status', name: '我的月度' },
    { key: 'year', name: '年度台账' },
    { key: 'report', name: '月度统计', admin: true },
    { key: 'projects', name: '项目库', admin: true },
    { key: 'users', name: '人员管理', admin: true },
    { key: 'monitor', name: '填报监控', admin: true },
    { key: 'approvals', name: '撤回审批', admin: true },
    { key: 'export', name: '数据导出', admin: true },
    { key: 'settings', name: '设置' }
  ];

  function buildTabs() {
    var isAdmin = S.user && S.user.isAdmin;
    var tabs = $('#tabs');
    tabs.innerHTML = VIEWS.filter(function (v) { return !v.admin || isAdmin; })
      .map(function (v) { return '<button data-view="' + v.key + '">' + v.name + '</button>'; }).join('');
    $$('#tabs button').forEach(function (b) {
      b.onclick = function () { switchView(b.getAttribute('data-view')); };
    });
  }

  function switchView(key) {
    S.view = key;
    $$('#tabs button').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-view') === key);
    });
    var map = {
      fill: viewFill, status: viewStatus, year: viewYear, report: viewReport,
      projects: viewProjects, users: viewUsers, monitor: viewMonitor,
      approvals: viewApprovals, export: viewExport, settings: viewSettings
    };
    (map[key] || viewFill)();
  }

  function setView(html) { $('#view').innerHTML = html; }

  /* ============================ ① 我的工时（明细条目） ============================ */
  function viewFill(periodStart) {
    /* 不传周期时交给服务端决定：默认落到「最近一个已经过完的周期」 */
    var ps = periodStart || S.periodStart || '';
    setView('<div class="empty">加载中…</div>');
    var url = '/api/period' + (ps ? '?periodStart=' + ps : '');
    api(url).then(function (j) {
      S.period = j.data;
      S.periodStart = j.data.periodStart;
      renderFill();
    }).catch(function (e) { setView('<div class="empty">' + esc(e.message) + '</div>'); });
  }

  function renderFill() {
    var d = S.period;
    var filledDays = d.daysFilled || 0;
    var workdays = d.workdaysTotal || 0;
    var pct = workdays ? Math.min(100, Math.round(filledDays / workdays * 100)) : 0;
    var allDays = workdays > 0 && filledDays >= workdays;
    var statusTag = d.submitted
      ? '<span class="tag green">已提交</span>'
      : (allDays ? '<span class="tag blue">待提交</span>' : '<span class="tag orange">填写中</span>');
    var extTag = d.periodExtended
      ? '<span class="tag orange">跨周 ' + d.periodDays + ' 天</span>'
      : '<span class="tag">' + d.periodDays + ' 天</span>';

    var hoursLine = '本期已填 <b>' + (d.totalHours || 0) + '</b> 小时';
    if (d.suggestedHours) {
      var diff = Math.round(((d.totalHours || 0) - d.suggestedHours) * 10) / 10;
      if (diff > 0) hoursLine += ' <span class="tag orange">比常规 ' + d.suggestedHours + 'h 多 ' + diff + 'h</span>';
      else if (diff < 0) hoursLine += ' <span class="tag">比常规 ' + d.suggestedHours + 'h 少 ' + (-diff) + 'h</span>';
      else hoursLine += ' <span class="tag green">与常规 ' + d.suggestedHours + 'h 一致</span>';
    }

    var html =
      '<div class="card">' +
        '<div class="weekbar">' +
          '<div style="min-width:0">' +
            '<div class="weektitle">' + esc(d.periodLabel) + ' ' + extTag +
              ' <span class="tag">第 ' + d.weekNumber + ' 周</span>' +
              (d.editable ? '' : ' <span class="tag orange">未结束 · 只读</span>') + '</div>' +
            '<div class="progress-line">' +
              '<div class="bar' + (allDays ? ' done' : '') + '"><i style="width:' + pct + '%"></i></div>' +
              '<span class="bar-num"><b>' + filledDays + '</b>/' + workdays + ' 个工作日已填</span>' +
            '</div>' +
          '</div>' +
          '<div class="weeknav">' +
            '<button class="btn sm" id="pPrev">← ' + esc(d.prevPeriodLabel) + '</button>' +
            '<button class="btn sm" id="pThis">该填这期</button>' +
            '<button class="btn sm" id="pNext">' + esc(d.nextPeriodLabel) + ' →</button>' +
          '</div>' +
        '</div>' +
        '<div class="row" style="margin-bottom:12px">' + statusTag +
          '<span class="muted fill-meta">' + hoursLine + '</span>' +
          '<span class="spacer"></span>' +
          (d.editable ? '<button class="btn sm" id="pCopy">从上一期复制</button>' : '') +
        '</div>' +
        (d.editable
          ? '<div class="notice info" style="margin-bottom:12px;font-size:12px">' +
              (d.isAux
                ? '你是<b>辅助人员</b>：每个工作日已自动填好「' +
                  esc(d.auxDefault ? d.auxDefault.workType : '非研发') + ' ' +
                  (d.auxDefault ? d.auxDefault.hours : 8) + ' 小时 · ' +
                  esc(d.auxDefault ? d.auxDefault.content : '部门行政管理事务') +
                  '」。如当天实际做了别的事（研发、开会、请假、加班），' +
                  '<b>直接改类型、工时和内容即可</b>，系统不会拦。'
                : '每天可以填多条（如"研发A 6 小时"+"部门会议 2 小时"），工时按实际填写，不需要凑 4+4。' +
                  '周末和节假日已自动预填「休假」，如果加班改成研发/非研发并填工时即可。') +
              '</div>'
          : '<div class="notice" style="margin-bottom:12px;font-size:13px;background:#fff7ed;' +
              'border-left:4px solid #f59e0b;padding:10px 12px">' +
              '<b>这一期还不能填。</b><br>' + esc(d.lockReason || '') +
              '<br><span class="muted">到这里看已填内容没问题；等这期过完再回来填。</span></div>') +
        '<div id="days"></div>' +
        '<div id="errBox"></div>' +
        submitNotice(d) +
        (d.canEdit
          ? '<div class="weekfoot">' +
              '<button class="btn" id="pSave">保存草稿</button>' +
              '<button class="btn primary" id="pSubmit">' +
                (d.submitted ? '更新并重新提交' : '提交本期') + '</button>' +
              (d.submitted && S.user && S.user.isAdmin
                ? '<button class="btn" id="pWithdraw">撤回（管理员）</button>' : '') +
            '</div>'
          : (d.submitted
              ? '<div class="weekfoot">' +
                  (d.withdrawPending
                    ? '<span class="muted">撤回申请待管理员审批（' +
                      esc(d.withdrawPending.reason) + '）</span>'
                    : '<button class="btn" id="pAskWithdraw">申请撤回</button>') +
                  '<span class="muted" style="margin-left:10px">已提交的内容不能直接改，需管理员审批</span>' +
                '</div>'
              : '<div class="weekfoot"><span class="muted">只读模式 · 不可编辑</span></div>')) +
      '</div>';

    setView(html);
    renderDays();

    $('#pPrev').onclick = function () { viewFill(d.prevPeriodStart); };
    $('#pNext').onclick = function () { viewFill(d.nextPeriodStart); };
    $('#pThis').onclick = function () { S.periodStart = ''; viewFill(); };
    if ($('#pCopy')) $('#pCopy').onclick = copyPrev;
    if ($('#pSave')) $('#pSave').onclick = function () { savePeriod(false); };
    if ($('#pSubmit')) $('#pSubmit').onclick = function () { savePeriod(true); };
    if ($('#pWithdraw')) $('#pWithdraw').onclick = withdraw;
    if ($('#pAskWithdraw')) $('#pAskWithdraw').onclick = askWithdraw;
    if (!d.canEdit) lockDays();
  }

  /* 已提交 / 待审批 / 被驳回 的提示条 */
  function submitNotice(d) {
    if (!d.submitted) return '';
    var me = S.user || {};
    if (d.withdrawPending) {
      return '<div class="notice" style="margin-bottom:12px;font-size:13px;background:#fff7ed;' +
        'border-left:4px solid #f59e0b;padding:10px 12px">' +
        '<b>撤回申请已提交，等管理员审批。</b><br>' +
        '原因：' + esc(d.withdrawPending.reason) +
        '　提交时间：' + esc(d.withdrawPending.createdAt || '') +
        '<br><span class="muted">审批通过后本期会变回草稿，你就能继续修改了。</span></div>';
    }
    if (d.lastWithdrawResult && d.lastWithdrawResult.status === '已驳回') {
      return '<div class="notice" style="margin-bottom:12px;font-size:13px;background:#fef2f2;' +
        'border-left:4px solid #ef4444;padding:10px 12px">' +
        '<b>上次撤回申请被驳回。</b>' +
        (d.lastWithdrawResult.note ? '<br>管理员说明：' + esc(d.lastWithdrawResult.note) : '') +
        '<br><span class="muted">如确有错误，可再次申请撤回。</span></div>';
    }
    if (me.isAdmin) {
      return '<div class="notice info" style="margin-bottom:12px;font-size:13px">' +
        '本期已提交。<b>管理员</b>可以直接修改并重新提交。</div>';
    }
    return '<div class="notice info" style="margin-bottom:12px;font-size:13px">' +
      '本期<b>已提交</b>，内容已锁定。如需更正请点「申请撤回」，管理员审批通过后才能修改。</div>';
  }

  /* 只读：把日历里的输入控件全部禁用，并隐藏"添加/删除"按钮（保留内容方便查看） */
  function lockDays() {
    var box = $('#days');
    if (!box) return;
    Array.prototype.forEach.call(box.querySelectorAll('input,select,button'), function (el) {
      el.disabled = true;
    });
    Array.prototype.forEach.call(box.querySelectorAll('[data-add],[data-act]'), function (el) {
      el.style.display = 'none';
    });
  }

  /* ---- 渲染每天 + 明细行 ---- */
  function renderDays() {
    var box = $('#days');
    box.innerHTML = S.period.days.map(function (day, di) {
      return dayHtml(day, di);
    }).join('');
    bindDays();
    updateFillSummary();
  }

  function dayHtml(day, di) {
    var items = day.items || [];
    var dayHours = items.reduce(function (a, it) {
      return a + (it.work_type === '休假' ? 0 : (parseFloat(it.hours) || 0));
    }, 0);
    var cls = 'daycard' + (day.isToday ? ' today' : '') + (day.isWorkday ? '' : ' off');
    var head = '<div class="dayhead">' +
      '<span class="dayname">' + esc(day.weekday) + ' ' + esc(day.date.slice(5)) + '</span>' +
      (!day.isWorkday ? '<span class="tag orange">休息日</span>' : '') +
      '<span class="spacer"></span>' +
      '<span class="dayhours">' + (dayHours ? dayHours + ' 小时' : '') + '</span>' +
      '<button class="btn sm" data-add="' + di + '">＋ 添加</button>' +
      '</div>';

    var rows = items.map(function (it, ii) { return itemHtml(it, di, ii); }).join('');
    return '<div class="' + cls + '">' + head + '<div class="items">' + rows + '</div></div>';
  }

  function itemHtml(it, di, ii) {
    var isRd = it.work_type === '研发';
    var isNrd = it.work_type === '非研发';
    var isLeave = it.work_type === '休假';
    var projOpts = '<option value="">选择项目…</option>' + (S.period.projects || []).map(function (p) {
      var sel = String(p.id) === String(it.project_id) ? ' selected' : '';
      var full = p.code + ' ' + p.name + (p.active === false ? '（已停用）' : '');
      // 选项文字太长会把下拉撑得很宽，这里按长度截断**仅用于显示**，
      // 真实项目名始终从 S.period.projects 取，数据不丢；
      // title 里放全称，鼠标悬停即可看完整。
      var short = full.length > 26 ? full.slice(0, 25) + '…' : full;
      return '<option value="' + p.id + '"' + sel + ' title="' + esc(full) + '">' +
        esc(short) + '</option>';
    }).join('');

    var hrs = (it.work_type === '休假') ? 0 : (it.hours === '' || it.hours == null ? '' : it.hours);

    return '<div class="item" data-d="' + di + '" data-i="' + ii + '">' +
      '<div class="seg">' +
        '<button type="button" data-act="rd" class="' + (isRd ? 'on-rd' : '') + '">研发</button>' +
        '<button type="button" data-act="nrd" class="' + (isNrd ? 'on-nrd' : '') + '">非研发</button>' +
        '<button type="button" data-act="leave" class="' + (isLeave ? 'on-leave' : '') + '">休假</button>' +
      '</div>' +
      (isRd ? '<select data-proj="1" class="mini-input" title="选择研发项目">' + projOpts + '</select>' : '') +
      '<input class="mini-input hours" data-field="hours" type="number" min="0" max="' +
        (S.period.rules.maxDailyHours || 24) + '" step="0.5" value="' + hrs + '"' +
        (isLeave ? ' disabled' : '') + ' title="工时（小时）">' +
      '<input class="mini-input content" data-field="content" type="text" value="' + esc(it.content) + '"' +
        ' placeholder="' + (isLeave ? '写清什么假，如 年假' : '做了什么、做出什么结果') + '">' +
      '<button class="btn sm danger rm" data-act="del" title="删除这条">✕</button>' +
      '</div>';
  }

  function bindDays() {
    var box = $('#days');
    /* 只有「按钮类」操作才走 click 重绘；input/select 一律不拦。
       历史 bug：select/input 也带 data-act，点一下就会被当成按钮触发 renderDays()，
       整个 DOM 重建 → 下拉展不开（要按住拖）、输入框光标丢失。 */
    var BUTTON_ACTS = { rd: 1, nrd: 1, leave: 1, del: 1 };

    box.onclick = function (e) {
      var el = e.target;
      // 表单控件自身的交互交给浏览器处理，绝不在这里重绘
      if (el && el.closest && el.closest('input,select,textarea,option')) return;

      var t = el.closest ? el.closest('[data-act],[data-add]') : null;
      if (!t) return;

      // 加一条
      if (t.hasAttribute('data-add')) {
        var di = +t.getAttribute('data-add');
        S.period.days[di].items.push({
          id: null, date: S.period.days[di].date, seq: 0, work_type: '',
          kind: '正常', hours: '', project_id: '', content: '', status: ''
        });
        renderDays();
        return;
      }

      var act0 = t.getAttribute('data-act');
      if (!BUTTON_ACTS[act0]) return;   // 不是按钮动作就不重绘

      var itemEl = t.closest('.item');
      if (!itemEl) return;
      var d2 = +itemEl.getAttribute('data-d'), i2 = +itemEl.getAttribute('data-i');
      var it = S.period.days[d2].items[i2];
      var act = t.getAttribute('data-act');

      if (act === 'rd') {
        it.work_type = '研发';
        if (!it.project_id && S.period.projects[0]) it.project_id = S.period.projects[0].id;
        if (it.hours === '' || it.hours == null || it.hours === 0) it.hours = 8;
      } else if (act === 'nrd') {
        it.work_type = '非研发';
        it.project_id = '';
        if (it.hours === '' || it.hours == null || it.hours === 0) it.hours = 8;
      } else if (act === 'leave') {
        it.work_type = '休假';
        it.project_id = '';
        it.hours = 0;
      } else if (act === 'del') {
        var arr = S.period.days[d2].items;
        if (arr.length <= 1) {
          arr[0] = { id: null, date: S.period.days[d2].date, seq: 0, work_type: '',
                     kind: '正常', hours: '', project_id: '', content: '', status: '' };
        } else {
          arr.splice(i2, 1);
        }
      }
      renderDays();
    };

    box.onchange = function (e) {
      var t = e.target;
      var itemEl = t.closest('.item');
      if (!itemEl) return;
      var d2 = +itemEl.getAttribute('data-d'), i2 = +itemEl.getAttribute('data-i');
      var it = S.period.days[d2].items[i2];
      if (t.hasAttribute('data-proj')) it.project_id = t.value;
      updateFillSummary();
    };

    box.oninput = function (e) {
      var t = e.target;
      var itemEl = t.closest('.item');
      if (!itemEl) return;
      var d2 = +itemEl.getAttribute('data-d'), i2 = +itemEl.getAttribute('data-i');
      var it = S.period.days[d2].items[i2];
      var act = t.getAttribute('data-field');
      if (act === 'hours') {
        it.hours = t.value;
        // 同步更新该天右上角的工时显示
        var dayEl = t.closest('.daycard');
        var dh = dayEl.querySelector('.dayhours');
        var sum = S.period.days[d2].items.reduce(function (a, x) {
          return a + (x.work_type === '休假' ? 0 : (parseFloat(x.hours) || 0));
        }, 0);
        if (dh) dh.textContent = sum ? Math.round(sum * 10) / 10 + ' 小时' : '';
      } else if (act === 'content') {
        it.content = t.value;
      }
      updateFillSummary();
    };
  }

  /* ---- 汇总行 ---- */
  function collectItems() {
    var out = [];
    S.period.days.forEach(function (day) {
      (day.items || []).forEach(function (it) {
        var has = it.work_type || (it.content && String(it.content).trim());
        if (!has) return;
        out.push({
          date: it.date, work_type: it.work_type || '', kind: it.kind || '正常',
          hours: it.work_type === '休假' ? 0 : it.hours,
          project_id: it.project_id || '', content: it.content || ''
        });
      });
    });
    return out;
  }

  function updateFillSummary() {
    var items = collectItems();
    var total = 0, rd = 0, nrd = 0;
    var seen = {};
    var workdaySet = {};
    S.period.days.forEach(function (d) {
      if (d.isWorkday) workdaySet[d.date] = 1;
    });
    items.forEach(function (it) {
      var h = it.work_type === '休假' ? 0 : (parseFloat(it.hours) || 0);
      total += h;
      if (it.work_type === '研发') rd += h;
      if (it.work_type === '非研发') nrd += h;
      // 只有工作日才算"已填天数"
      if (workdaySet[it.date]) seen[it.date] = 1;
    });
    var days = Object.keys(seen).length;
    var d = S.period;
    var workdays = d.workdaysTotal || 0;
    var pct = workdays ? Math.min(100, Math.round(days / workdays * 100)) : 0;
    var bar = $('.bar');
    if (bar) {
      bar.classList.toggle('done', workdays > 0 && days >= workdays);
      bar.firstChild.style.width = pct + '%';
    }
    var num = $('.bar-num');
    if (num) {
      var numTxt = days + '/' + workdays;
      if (num.getAttribute('data-v') !== numTxt) {
        num.setAttribute('data-v', numTxt);
        num.innerHTML = '<b>' + days + '</b>/' + workdays + ' 个工作日已填';
      }
    }
    var meta = $('.fill-meta');
    if (meta) {
      var t1 = Math.round(total * 10) / 10;
      var sug = d.suggestedHours || 0;
      var s = '本期已填 <b>' + t1 + '</b> 小时（研发 ' + Math.round(rd * 10) / 10 +
              ' / 非研发 ' + Math.round(nrd * 10) / 10 + '）';
      if (sug) {
        var df = Math.round((t1 - sug) * 10) / 10;
        if (df > 0) s += ' <span class="tag orange">比常规 ' + sug + 'h 多 ' + df + 'h</span>';
        else if (df < 0) s += ' <span class="tag">比常规 ' + sug + 'h 少 ' + (-df) + 'h</span>';
        else s += ' <span class="tag green">与常规 ' + sug + 'h 一致</span>';
      }
      // 内容没变就不重写 DOM：避免每敲一个字都触发一次整行重排
      if (meta.getAttribute('data-v') !== s) {
        meta.setAttribute('data-v', s);
        meta.innerHTML = s;
      }
    }
    d.totalHours = Math.round(total * 10) / 10;
    d.daysFilled = days;
  }

  function savePeriod(submit) {
    var items = collectItems();
    if (!items.length) { toast('还没有填写内容', 'err'); return; }
    var btns = [$('#pSave'), $('#pSubmit')];
    btns.forEach(function (b) { if (b) b.disabled = true; });
    api('/api/period/save', { body: { periodStart: S.periodStart, items: items, submit: !!submit } })
      .then(function (j) {
        toast(j.data.message + (j.data.warning ? '｜' + j.data.warning : ''), 'ok');
        viewFill(S.periodStart);
      })
      .catch(function (e) {
        btns.forEach(function (b) { if (b) b.disabled = false; });
        showErrors(e); toast(e.message, 'err');
      });
  }

  function showErrors(e) {
    var box = $('#errBox'); if (!box) return;
    var errs = (e.details && e.details.errors) || [];
    if (!errs.length) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="errlist">' + errs.map(function (x) {
      return '<div>· ' + esc(x.message) + '</div>';
    }).join('') + '</div>';
    errs.forEach(function (x) {
      if (x.index === null || x.index === undefined) return;
      var date = String(x.path || '').split(' ')[0];
      S.period.days.forEach(function (day, di) {
        if (day.date !== date) return;
        var el = document.querySelectorAll('.daycard')[di];
        if (el) el.classList.add('err');
      });
    });
    box.scrollIntoView({ block: 'nearest' });
  }

  /* 管理员直接撤回 */
  function withdraw() {
    if (!confirm('确认撤回本期填报？撤回后状态变为草稿，可继续修改。')) return;
    api('/api/period/withdraw', { body: { periodStart: S.periodStart } })
      .then(function (j) { toast(j.data.message, 'ok'); viewFill(S.periodStart); })
      .catch(function (e) { toast(e.message, 'err'); });
  }

  /* 普通成员：申请撤回（需管理员审批） */
  function askWithdraw() {
    var reason = prompt('请简单说明撤回原因（管理员审批时会看）：', '');
    if (reason === null) return;
    reason = String(reason).trim();
    if (reason.length < 2) { toast('请至少写 2 个字的原因', 'err'); return; }
    api('/api/period/withdraw',
        { body: { periodStart: S.periodStart, reason: reason } })
      .then(function (j) { toast(j.data.message, 'ok'); viewFill(S.periodStart); })
      .catch(function (e) { toast(e.message, 'err'); });
  }

  function copyPrev() {
    if (!confirm('把上一周期的记录复制到本期（跳过本期已填的日期，复制后为草稿）？')) return;
    api('/api/period/copy-prev', { body: { periodStart: S.periodStart } })
      .then(function (j) { toast(j.data.message, 'ok'); viewFill(S.periodStart); })
      .catch(function (e) { toast(e.message, 'err'); });
  }

  /* ============================ ② 我的月度 ============================ */
  function viewStatus() {
    setView('<div class="empty">加载中…</div>');
    var month = S.month || thisMonth();
    api('/api/my-status?month=' + month).then(function (j) {
      var d = j.data;
      var html = '<div class="card">' +
        '<div class="card-head">' +
          '<div class="card-title">我的月度填报 <small>' + esc(d.monthLabel) +
            (d.monthRange ? ' · ' + esc(d.monthRange) : '') + '</small></div>' +
          '<input type="month" id="stMonth" value="' + d.month + '" class="mini-input">' +
        '</div>' +
        '<div class="stats">' +
          stat('合计工时', (d.totalHours || 0) + '<small>h</small>') +
          stat('记录条数', (d.totalItems || 0) + '<small>条</small>') +
          stat('已填期数', d.periods.filter(function (x) { return x.complete; }).length +
               '<small>/' + d.periods.length + '</small>') +
          stat('未提交期数', d.pendingPeriods.length + '<small>期</small>') +
        '</div>' +
        (d.fillablePeriodStart
          ? '<div class="notice info" style="margin-bottom:10px;font-size:12px">' +
              '按「下周填本周」规则，现在该填的是 <b>' +
              esc(d.fillablePeriodStart) + ' ~ ' + esc(d.fillablePeriodEnd) + '</b>' +
              '（这一期已经结束）。还没结束的周期只能查看、不能填。' +
              '<button class="btn sm" id="stGoFill" style="margin-left:8px">去填这期</button>' +
            '</div>'
          : '') +
        '<div class="tbl-wrap"><table><thead><tr>' +
          '<th>填报周期</th><th>天数</th><th>记录条数</th><th>合计工时</th><th>状态</th><th>操作</th>' +
        '</tr></thead><tbody>' +
        d.periods.map(function (p) {
          var locked = p.editable === false;
          return '<tr><td>' + esc(p.periodLabel) + (p.extended ? ' <span class="tag orange">跨周</span>' : '') +
            '</td><td class="num">' + p.dayCount + '</td>' +
            '<td class="num">' + (p.items || 0) + '</td>' +
            '<td class="num">' + (p.hours || 0) + '</td>' +
            '<td>' + (locked ? '<span class="tag">未结束</span>'
              : (p.submitted ? '<span class="tag green">已提交</span>'
                : (p.complete ? '<span class="tag blue">待提交</span>'
                  : '<span class="tag orange">未填写</span>'))) + '</td>' +
            '<td><button class="btn sm" data-ps="' + p.periodStart + '">' +
              (locked ? '查看' : '去填写') + '</button></td></tr>';
        }).join('') +
        '</tbody></table></div></div>';
      setView(html);
      $('#stMonth').onchange = function () { S.month = this.value; viewStatus(); };
      if ($('#stGoFill')) {
        $('#stGoFill').onclick = function () {
          S.periodStart = d.fillablePeriodStart; switchView('fill');
        };
      }
      $$('[data-ps]').forEach(function (b) {
        b.onclick = function () { S.periodStart = b.getAttribute('data-ps'); switchView('fill'); };
      });
    }).catch(function (e) { setView('<div class="empty">' + esc(e.message) + '</div>'); });
  }

  /* ============================ ③ 年度台账 ============================ */
  function viewYear() {
    setView('<div class="empty">加载中…</div>');
    var isAdmin = S.user.isAdmin;
    var url = '/api/year?year=' + S.year + (S.yearUser ? '&userId=' + S.yearUser : '');
    Promise.all([
      api(url),
      isAdmin ? api('/api/admin/users') : Promise.resolve({ users: [] })
    ]).then(function (res) {
      var d = res[0].data;
      var users = res[1].users || [];
      var head = '<div class="card"><div class="card-head">' +
        '<div class="card-title">年度工时台账 <small>工资月口径（' +
          esc(monthRangeText(d.year + '-06')) + ' 之类，上月26日-当月25日）</small></div>' +
        '<div class="row">' +
          '<select id="yrSel" class="mini-input">' +
          [0, 1, 2, 3].map(function (i) {
            var y = new Date().getFullYear() - i;
            return '<option value="' + y + '"' + (y === d.year ? ' selected' : '') + '>' + y + ' 年</option>';
          }).join('') + '</select>' +
          (isAdmin
            ? '<select id="yrUser" class="mini-input"><option value="">全员汇总</option>' +
              users.filter(function (u) { return u.trackHours; }).map(function (u) {
                return '<option value="' + u.id + '"' + (String(u.id) === String(S.yearUser) ? ' selected' : '') +
                  '>' + esc(u.name) + '</option>';
              }).join('') + '</select>'
            : '') +
          '<button class="btn sm primary" id="yrExport">导出 Excel</button>' +
        '</div></div>';

      var body = '';
      if (d.mode === 'overview') {
        var t = d.totals;
        body = '<div class="stats">' +
            stat('覆盖人数', t && d.rows.length + '<small>人</small>') +
            stat('研发工时', t.rd + '<small>h</small>') +
            stat('非研发工时', t.nrd + '<small>h</small>') +
            stat('合计工时', t.total + '<small>h</small>') +
            stat('研发占比', t.rdRatio + '<small>%</small>') +
            stat('填报率', t.rate + '<small>%</small>') +
          '</div>' +
          '<div class="tbl-wrap"><table><thead><tr>' +
            '<th>姓名</th><th>岗位</th><th>研发工时</th><th>非研发工时</th><th>合计工时</th>' +
            '<th>研发占比</th><th>应填半天</th><th>实填半天</th><th>填报率</th></tr></thead><tbody>' +
          d.rows.map(function (r) {
            return '<tr><td>' + esc(r.name) + '</td><td>' + esc(r.jobTitle || '—') + '</td>' +
              '<td class="num">' + r.rd + '</td><td class="num">' + r.nrd + '</td>' +
              '<td class="num">' + r.total + '</td><td class="num">' + r.rdRatio + '%</td>' +
              '<td class="num">' + r.quota + '</td><td class="num">' + r.units + '</td>' +
              '<td>' + (r.rate >= 100 ? '<span class="tag green">' + r.rate + '%</span>'
                : '<span class="tag ' + (r.rate > 0 ? 'orange' : 'red') + '">' + r.rate + '%</span>') + '</td></tr>';
          }).join('') +
          '</tbody><tfoot><tr><td>合计</td><td>' + d.rows.length + ' 人</td>' +
            '<td class="num">' + t.rd + '</td><td class="num">' + t.nrd + '</td>' +
            '<td class="num">' + t.total + '</td><td class="num">' + t.rdRatio + '%</td>' +
            '<td class="num">' + t.quota + '</td><td class="num">' + t.units + '</td>' +
            '<td class="num">' + t.rate + '%</td></tr></tfoot></table></div>';
      } else {
        var tt = d.totals;
        body = '<div class="notice info">' + esc(d.name) + '　' + esc(d.jobTitle || '未填岗位') +
            (d.dept ? '　' + esc(d.dept) : '') + '　' + d.year + ' 年度</div>' +
          '<div class="stats">' +
            stat('全年研发', tt.rd + '<small>h</small>') +
            stat('全年非研发', tt.nrd + '<small>h</small>') +
            stat('全年合计', tt.total + '<small>h</small>') +
            stat('研发占比', tt.rdRatio + '<small>%</small>') +
            stat('全年填报率', tt.rate + '<small>%</small>') +
          '</div>' +
          '<div class="tbl-wrap"><table><thead><tr>' +
            '<th>工资月</th><th>研发工时</th><th>非研发工时</th><th>合计工时</th>' +
            '<th>研发占比</th><th>应填半天</th><th>实填半天</th><th>填报率</th></tr></thead><tbody>' +
          d.months.map(function (m) {
            return '<tr><td>' + m.month + '</td>' +
              '<td class="num">' + m.rd + '</td><td class="num">' + m.nrd + '</td>' +
              '<td class="num">' + m.total + '</td><td class="num">' + m.rdRatio + '%</td>' +
              '<td class="num">' + m.quota + '</td><td class="num">' + m.units + '</td>' +
              '<td>' + (m.rate >= 100 ? '<span class="tag green">' + m.rate + '%</span>'
                : (m.quota ? '<span class="tag orange">' + m.rate + '%</span>' : '<span class="tag">—</span>')) + '</td></tr>';
          }).join('') +
          '</tbody><tfoot><tr><td>全年合计</td>' +
            '<td class="num">' + tt.rd + '</td><td class="num">' + tt.nrd + '</td>' +
            '<td class="num">' + tt.total + '</td><td class="num">' + tt.rdRatio + '%</td>' +
            '<td class="num">' + tt.quota + '</td><td class="num">' + tt.units + '</td>' +
            '<td class="num">' + tt.rate + '%</td></tr></tfoot></table></div>';

        if (d.projects && d.projects.length) {
          body += '<div class="card-title" style="font-size:14px;margin:18px 0 8px">年度研发项目分布</div>' +
            '<div class="tbl-wrap"><table><thead><tr>' +
              '<th>项目编号</th><th class="left">项目名称</th><th>研发工时</th>' +
              '<th>占全年研发比例</th><th>涉及月份</th><th>工时人次</th></tr></thead><tbody>' +
            d.projects.map(function (p) {
              return '<tr><td>' + esc(p.code) + '</td>' +
                nameCell(p.name) +
                '<td class="num">' + p.rd + '</td><td class="num">' + p.ratio + '%</td>' +
                '<td class="num">' + p.monthCount + '</td><td class="num">' + p.times + '</td></tr>';
            }).join('') + '</tbody></table></div>';
        }
      }

      setView(head + body + '</div>');

      $('#yrSel').onchange = function () { S.year = +this.value; viewYear(); };
      if ($('#yrUser')) {
        $('#yrUser').onchange = function () { S.yearUser = this.value; viewYear(); };
      }
      $('#yrExport').onclick = function () {
        var u = '/api/year/export?year=' + S.year + (S.yearUser ? '&userId=' + S.yearUser : '');
        window.location.href = u;
        toast('正在生成 Excel…');
      };
    }).catch(function (e) { setView('<div class="empty">' + esc(e.message) + '</div>'); });
  }

  /* ============================ ④ 月度统计 ============================ */
  function viewReport() {
    setView('<div class="empty">加载中…</div>');
    var month = S.month || thisMonth();
    var ex = (S.excluded || []).join(',');
    api('/api/admin/preview?month=' + month + (ex ? '&excludeUserIds=' + ex : ''))
      .then(function (j) { renderReport(j.data); })
      .catch(function (e) { setView('<div class="empty">' + esc(e.message) + '</div>'); });
  }

  function renderReport(d) {
    var s = d.stats, bd = d.breakdown || {};
    var members = d.members || [];
    var excluded = S.excluded || [];
    var selectedCount = members.filter(function (m) { return excluded.indexOf(m.id) < 0; }).length;
    var pfHtml = '<details class="pf-box" id="pfBox">' +
      '<summary>人员筛选：已选 <b>' + selectedCount + '</b> / ' + members.length + ' 人' +
        (excluded.length ? '（已排除 ' + excluded.length + ' 人）' : '') + '</summary>' +
      '<div class="pf-actions">' +
        '<button class="btn sm" id="pfAll">全选</button>' +
        '<button class="btn sm" id="pfNone">全不选</button>' +
        '<span class="muted">取消勾选的人不计入本次统计；人员汇总、工时构成、填报率都会重算</span>' +
      '</div>' +
      '<div class="pf-list">' +
        members.map(function (m) {
          var on = excluded.indexOf(m.id) < 0;
          return '<label class="pf-item"><input type="checkbox" data-mid="' + m.id + '"' +
            (on ? ' checked' : '') + '><span>' + esc(m.name) +
            ' <span class="muted">' + esc(m.jobTitle || '未填岗位') + '</span>' +
            ' <span class="muted">本月 ' + (m.rd + m.nrd) + 'h / ' + m.units + ' 半天</span></span></label>';
        }).join('') +
      '</div>' +
    '</details>';
    var html = '<div class="card">' +
      '<div class="card-head">' +
        '<div class="card-title">月度工时统计</div>' +
        '<div class="row">' +
          '<select id="rpMonth" class="mini-input">' +
          (d.months || []).map(function (m) {
            return '<option value="' + m + '"' + (m === d.month ? ' selected' : '') + '>' + m + '</option>';
          }).join('') + '</select>' +
          '<span class="muted" id="rpRange">' + esc(d.monthRange || monthRangeText(d.month)) + '</span>' +
          '<button class="btn sm" id="rpPreview">刷新预览</button>' +
          '<button class="btn sm primary" id="rpGen">⚡ 一键生成统计表</button>' +
        '</div>' +
      '</div>' +
      '<div class="stats">' +
        stat('覆盖人数', s.headcount + '<small>人</small>') +
        stat('记录条数', s.rows + '<small>条</small>') +
        stat('研发工时', s.rdTotal + '<small>h</small>') +
        stat('非研发工时', s.nrdTotal + '<small>h</small>') +
        stat('合计工时', s.totalHours + '<small>h</small>') +
        stat('研发占比', s.rdRatio + '<small>%</small>') +
        stat('填写率', (s.fillRate || 0) + '<small>%</small>') +
      '</div>' +
      pfHtml +
      '<div class="row" style="margin-bottom:14px">' +
        (s.fillRate < 100
          ? '<span class="tag orange">填写率 ' + s.fillRate + '%，还有 ' +
            (s.quotaDaysTotal - s.daysTotal) + ' 人天未填，出表前建议先催办</span>'
          : '<span class="tag green">填报完整</span>') +
        '<span class="spacer"></span>' +
        '<a class="btn sm" href="/api/admin/report/download?month=' + d.month + '">下载上次生成的文件</a>' +
      '</div>';

    // 填报周期
    if (d.periods && d.periods.length) {
      html += '<div class="card-title" style="font-size:14px;margin:6px 0 8px">填报周期（跨周/跨月的天数已并入相邻周期）</div>' +
        '<div class="tbl-wrap"><table><thead><tr>' +
          '<th>周期起</th><th>周期止</th><th>天数</th><th>工作日</th><th>覆盖人数</th>' +
          '<th>条目数</th><th>合计工时</th>' +
        '</tr></thead><tbody>' +
        d.periods.map(function (p) {
          var ext = p.dayCount > 7;
          return '<tr><td>' + esc(p.periodStart) + '</td><td>' + esc(p.periodEnd) + '</td>' +
            '<td class="num">' + p.dayCount + (ext ? ' <span class="tag orange">跨周延伸</span>' : '') + '</td>' +
            '<td class="num">' + (p.workdays || 0) + '</td>' +
            '<td class="num">' + (p.people || 0) + '</td>' +
            '<td class="num">' + (p.filled || 0) + '</td>' +
            '<td class="num">' + (p.hours || 0) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }

    html += '<div class="card-title" style="font-size:14px;margin:18px 0 8px">人员汇总</div>' +
      '<div class="tbl-wrap"><table><thead><tr>' +
        '<th>姓名</th><th>岗位</th><th>研发工时</th><th>非研发工时</th><th>合计工时</th>' +
        '<th>研发占比</th><th>应出勤天数</th><th>实填天数</th><th>填写率</th>' +
        '</tr></thead><tbody>' +
      d.perPerson.map(function (p) {
        return '<tr><td>' + esc(p.name) + '</td><td>' + esc(p.jobTitle || '—') + '</td>' +
          '<td class="num">' + p.rd + '</td><td class="num">' + p.nrd + '</td>' +
          '<td class="num">' + p.total + '</td><td class="num">' + p.rdRatio + '%</td>' +
          '<td class="num">' + (p.quotaDays || 0) + '</td><td class="num">' + (p.days || 0) + '</td>' +
          '<td>' + (p.rate >= 100 ? '<span class="tag green">' + p.rate + '%</span>'
            : '<span class="tag ' + (p.rate > 0 ? 'orange' : 'red') + '">' + p.rate + '%</span>') + '</td>' +
          '</tr>';
      }).join('') + '</tbody></table></div>';

    // 项目汇总（含财务归集口径）
    html += '<div class="card-title" style="font-size:14px;margin:18px 0 8px">项目汇总 <small class="muted">（只有研发工时计入项目）</small></div>' +
      '<div class="tbl-wrap"><table><thead><tr>' +
        '<th>项目编号</th><th class="left">项目名称</th><th>参与人数</th><th>研发工时</th>' +
        '<th>非研发工时</th><th>总工时</th><th>研发工时占比</th><th>占全月工时比例</th><th>工时人次</th>' +
      '</tr></thead><tbody>' +
      (d.perProject.length ? d.perProject.map(function (p) {
        return '<tr><td>' + esc(p.code) + '</td>' + nameCell(p.name) +
          '<td class="num">' + p.people + '</td><td class="num">' + p.rd + '</td>' +
          '<td class="num">' + p.nrd + '</td><td class="num">' + p.total + '</td>' +
          '<td class="num">' + p.rdRatio + '%</td>' +
          '<td class="num"><b>' + p.ratioOfMonthTotal + '%</b></td>' +
          '<td class="num">' + p.times + '</td></tr>';
      }).join('') : '<tr><td colspan="9" class="muted">本月还没有研发工时</td></tr>') +
      '</tbody>' + (function () {
        var trd = 0, tnrd = 0, ttimes = 0;
        d.perProject.forEach(function (p) {
          trd += p.rd; tnrd += p.nrd; ttimes += p.times;
        });
        var tall = trd + tnrd;
        var gPct = tall ? Math.round(trd / tall * 1000) / 10 : 0;
        var hPct = bd.totalHours ? Math.round(trd / bd.totalHours * 1000) / 10 : 0;
        return '<tfoot><tr><td>合计</td><td>' + d.perProject.length + ' 个项目</td>' +
          '<td class="num">' + (s.projectPeople || '—') + '</td>' +
          '<td class="num">' + trd + '</td><td class="num">' + tnrd + '</td>' +
          '<td class="num">' + tall + '</td>' +
          '<td class="num">' + gPct + '%</td>' +
          '<td class="num"><b>' + hPct + '%</b></td>' +
          '<td class="num">' + ttimes + '</td></tr></tfoot>';
      })() + '</table></div>' +
      '<div class="notice info" style="margin-top:12px">工时构成：全月总工时 <b>' + (bd.totalHours || 0) +
        '</b> 小时 — 研发 <b>' + (bd.rdHours || 0) + '</b> 小时（占 ' + (bd.rdRatio || 0) +
        '%）、非研发 <b>' + (bd.nrdHours || 0) + '</b> 小时（占 ' + (bd.nrdRatio || 0) +
        '%）' +
        (s.leaveTotal ? '；另有休假 <b>' + s.leaveTotal + '</b> 小时（0 工时）' : '') +
        '。「研发工时占比」= 本项目研发工时 ÷ 本项目总工时；「占全月工时比例」= 本项目研发工时 ÷ 全月总工时，可直接作为研发费用归集比例。合计行为按列求和。</div>';

    html += '<div class="card-title" style="font-size:14px;margin:18px 0 8px">明细预览（前 20 条）</div>' +
      '<div class="tbl-wrap"><table><thead><tr>' +
        '<th>日期</th><th>姓名</th><th>岗位</th><th>项目编号</th><th class="left">项目名称</th>' +
        '<th>研发工时</th><th>非研发工时</th><th class="left">工作内容</th></tr></thead><tbody>' +
      (d.detailSample.length ? d.detailSample.map(function (x) {
        return '<tr><td>' + esc(x.date) + '</td><td>' + esc(x.name) + '</td><td>' + esc(x.jobTitle || '—') + '</td>' +
          '<td>' + esc(x.projectCode) + '</td>' + nameCell(x.projectName, '', 'narrow') +
          '<td class="num">' + x.rdHours + '</td><td class="num">' + x.nrdHours + '</td>' +
          '<td class="left" style="white-space:normal;max-width:320px">' + esc(x.content) + '</td></tr>';
      }).join('') : '<tr><td colspan="8" class="muted">本月还没有工时记录</td></tr>') +
      '</tbody></table></div></div>';

    setView(html);

    $('#rpMonth').onchange = function () { S.month = this.value; S.excluded = []; viewReport(); };
    $('#rpPreview').onclick = function () { viewReport(); };

    if ($('#pfAll')) $('#pfAll').onclick = function () { S.excluded = []; viewReport(); };
    if ($('#pfNone')) $('#pfNone').onclick = function () {
      S.excluded = members.map(function (m) { return m.id; }); viewReport();
    };
    $$('#pfBox input[data-mid]').forEach(function (cb) {
      cb.onchange = function () {
        var id = +cb.getAttribute('data-mid');
        var ex = (S.excluded || []).slice();
        var i = ex.indexOf(id);
        if (cb.checked) { if (i >= 0) ex.splice(i, 1); }
        else if (i < 0) { ex.push(id); }
        S.excluded = ex;
        viewReport();
      };
    });
    $('#rpGen').onclick = function () {
      var m = $('#rpMonth').value;
      var btn = this; btn.disabled = true; btn.textContent = '生成中…';
      api('/api/admin/report', { body: { month: m, excludeUserIds: S.excluded || [] } }).then(function (r) {
        var g = r.data;
        btn.disabled = false; btn.textContent = '⚡ 一键生成统计表';
        toast('已生成 ' + g.fileName, 'ok');
        modal({
          title: '月度统计表已生成',
          body: '<p style="margin:0 0 12px">' + esc(g.fileName) + '</p>' +
            '<p class="muted">明细 ' + g.stats.rows + ' 条 · ' + g.stats.headcount + ' 人 · 合计 ' +
            g.stats.totalHours + ' 小时 · 研发占比 ' + g.stats.rdRatio + '%</p>' +
            '<p><a class="btn primary" href="' + g.downloadUrl + '">立即下载 Excel</a></p>',
          okText: '关闭'
        });
      }).catch(function (e) {
        btn.disabled = false; btn.textContent = '⚡ 一键生成统计表';
        toast(e.message, 'err');
      });
    };
  }

  /* ============================ 撤回审批（管理员） ============================ */
  function viewApprovals() {
    var showAll = !!S.apprAll;
    setView('<div class="empty">加载中…</div>');
    api('/api/admin/withdraw-requests' + (showAll ? '?all=1' : '')).then(function (j) {
      var rows = (j.data && j.data.requests) || [];
      var html = '<div class="card">' +
        '<div class="card-head">' +
          '<div class="card-title">撤回审批 <small>已提交的工时不能自己改，需管理员同意</small></div>' +
          '<div class="row">' +
            '<button class="btn sm" id="apToggle">' +
              (showAll ? '只看待审批' : '看全部（含已处理）') + '</button>' +
            '<button class="btn sm" id="apRefresh">刷新</button>' +
          '</div>' +
        '</div>' +
        '<div class="stats">' +
          stat('待审批', rows.filter(function (r) {
            return r.status === '待审批';
          }).length + '<small>条</small>') +
          stat('列表条数', rows.length + '<small>条</small>') +
        '</div>' +
        (rows.length
          ? '<div class="tbl-wrap"><table><thead><tr>' +
              '<th>申请人</th><th>周期</th><th class="left">撤回原因</th>' +
              '<th>申请时间</th><th>状态</th><th>操作</th>' +
            '</tr></thead><tbody>' +
            rows.map(function (r) {
              var tag = r.status === '待审批' ? '<span class="tag orange">待审批</span>'
                : r.status === '已同意' ? '<span class="tag green">已同意</span>'
                : r.status === '已驳回' ? '<span class="tag red">已驳回</span>'
                : '<span class="tag">' + esc(r.status) + '</span>';
              return '<tr><td>' + esc(r.name) +
                  ' <span class="muted">' + esc(r.jobTitle || '') + '</span></td>' +
                '<td>' + esc(r.periodStart) + ' ~ ' + esc(r.periodEnd) + '</td>' +
                '<td class="left" style="white-space:normal;max-width:280px">' +
                  esc(r.reason) + '</td>' +
                '<td class="muted">' + esc(r.createdAt || '') + '</td>' +
                '<td>' + tag + (r.decideNote
                  ? '<br><span class="muted">' + esc(r.decideNote) + '</span>' : '') + '</td>' +
                '<td>' + (r.status === '待审批'
                  ? '<button class="btn sm primary" data-ap="' + r.id + '">同意</button> ' +
                    '<button class="btn sm" data-rj="' + r.id + '">驳回</button>'
                  : '<span class="muted">—</span>') + '</td></tr>';
            }).join('') +
            '</tbody></table></div>'
          : '<div class="empty">' + (showAll ? '还没有任何撤回申请'
              : '没有待审批的撤回申请') + '</div>') +
        '</div>';
      setView(html);

      $('#apToggle').onclick = function () { S.apprAll = !showAll; viewApprovals(); };
      $('#apRefresh').onclick = function () { viewApprovals(); };
      $$('[data-ap]').forEach(function (b) {
        b.onclick = function () { decideWd(+b.getAttribute('data-ap'), true); };
      });
      $$('[data-rj]').forEach(function (b) {
        b.onclick = function () { decideWd(+b.getAttribute('data-rj'), false); };
      });
    }).catch(function (e) {
      setView('<div class="empty">' + esc(e.message) + '</div>');
    });
  }

  function decideWd(id, approve) {
    var note = '';
    if (!approve) {
      note = prompt('驳回原因（会给申请人看到）：', '') ;
      if (note === null) return;
    } else if (!confirm('同意后，该期会变回草稿，申请人可以继续修改。确定同意吗？')) {
      return;
    }
    api('/api/admin/withdraw-decide',
        { body: { id: id, approve: approve, note: note || '' } })
      .then(function (j) { toast(j.data.message, 'ok'); viewApprovals(); })
      .catch(function (e) { toast(e.message, 'err'); });
  }

  /* ============================ ⑤ 数据导出（原始记录留底） ============================ */
  function viewExport() {
    var mode = S.exportMode || 'month';
    var html = '<div class="card">' +
      '<div class="card-head">' +
        '<div class="card-title">数据导出 <small>每周每人的原始记录，用于留底存档</small></div>' +
      '</div>' +
      '<div class="field" style="max-width:560px">' +
        '<label>导出范围</label>' +
        '<div class="row" style="margin-bottom:10px">' +
          '<label class="radio"><input type="radio" name="exMode" value="month"' +
            (mode === 'month' ? ' checked' : '') + '> 按月份</label>' +
          '<label class="radio"><input type="radio" name="exMode" value="period"' +
            (mode === 'period' ? ' checked' : '') + '> 按填报周期</label>' +
          '<label class="radio"><input type="radio" name="exMode" value="range"' +
            (mode === 'range' ? ' checked' : '') + '> 按日期区间</label>' +
          '<label class="radio"><input type="radio" name="exMode" value="all"' +
            (mode === 'all' ? ' checked' : '') + '> 全部</label>' +
        '</div>' +
        '<div id="exParams" class="row" style="margin-bottom:10px"></div>' +
        '<label>文件格式</label>' +
        '<div class="row" style="margin-bottom:14px">' +
          '<label class="radio"><input type="radio" name="exFmt" value="xlsx"' +
            (S.exportFormat !== 'csv' ? ' checked' : '') + '> Excel（含 3 个 Sheet）</label>' +
          '<label class="radio"><input type="radio" name="exFmt" value="csv"' +
            (S.exportFormat === 'csv' ? ' checked' : '') + '> CSV（通用）</label>' +
        '</div>' +
        '<div class="row">' +
          '<button class="btn" id="exPreview">先预览</button>' +
          '<button class="btn primary" id="exDownload">下载导出文件</button>' +
        '</div>' +
      '</div>' +
      '<div class="notice info" style="margin-top:16px">' +
        '导出内容包含：序号、填报周期起止、日期、星期、时段、姓名、账号、岗位、部门、工时属性、' +
        '研发项目编号、项目名称、研发工时、非研发工时、具体工作内容、状态、填报时间。' +
        'Excel 版本另附「按人汇总」「按周期汇总」两个 Sheet。</div>' +
      '<div id="exResult"></div></div>';
    setView(html);

    function renderParams() {
      var box = $('#exParams');
      if (S.exportMode === 'month') {
        box.innerHTML = '<input type="month" id="exMonth" class="mini-input" value="' +
          (S.exportMonth || thisMonth()) + '">';
      } else if (S.exportMode === 'period') {
        box.innerHTML = '<input type="date" id="exPeriod" class="mini-input" value="' +
          (S.exportPeriod || todayStr()) + '">' +
          '<span class="muted">选该周期内任意一天即可，系统会自动换算成整个周期</span>';
      } else if (S.exportMode === 'range') {
        box.innerHTML = '<input type="date" id="exFrom" class="mini-input" value="' +
          (S.exportFrom || thisMonth() + '-01') + '"> 至 ' +
          '<input type="date" id="exTo" class="mini-input" value="' +
          (S.exportTo || todayStr()) + '">';
      } else {
        box.innerHTML = '<span class="muted">导出全部历史记录（数据量大的话建议按月导出）</span>';
      }
    }
    renderParams();

    $$('input[name=exMode]').forEach(function (r) {
      r.onchange = function () { S.exportMode = this.value; viewExport(); };
    });
    $$('input[name=exFmt]').forEach(function (r) {
      r.onchange = function () { S.exportFormat = this.value; };
    });

    function buildQuery(fmt) {
      var q = '?format=' + fmt;
      if (S.exportMode === 'month') {
        var m = $('#exMonth') ? $('#exMonth').value : thisMonth();
        S.exportMonth = m; q += '&month=' + m;
      } else if (S.exportMode === 'period') {
        var p = $('#exPeriod') ? $('#exPeriod').value : todayStr();
        S.exportPeriod = p; q += '&period=' + p;
      } else if (S.exportMode === 'range') {
        var f = $('#exFrom') ? $('#exFrom').value : '';
        var t = $('#exTo') ? $('#exTo').value : '';
        S.exportFrom = f; S.exportTo = t;
        q += '&from=' + f + '&to=' + t;
      }
      return q;
    }

    $('#exPreview').onclick = function () {
      var btn = this; btn.disabled = true;
      api('/api/admin/export/raw' + buildQuery('json')).then(function (j) {
        btn.disabled = false;
        var d = j.data;
        var box = $('#exResult');
        if (!d.count) { box.innerHTML = '<div class="empty">该范围内没有工时记录</div>'; return; }
        box.innerHTML = '<div class="card-title" style="font-size:14px;margin:18px 0 8px">' +
            '共 ' + d.count + ' 条记录' + (d.truncated ? '（仅预览前 200 条）' : '') + '</div>' +
          '<div class="tbl-wrap"><table><thead><tr>' +
            '<th>周期</th><th>日期</th><th>时段</th><th>姓名</th><th>岗位</th>' +
            '<th>工时属性</th><th>项目</th><th>研发</th><th>非研发</th><th class="left">工作内容</th>' +
          '</tr></thead><tbody>' +
          d.rows.map(function (r) {
            return '<tr><td class="muted">' + esc(r.periodStart.slice(5)) + '~' + esc(r.periodEnd.slice(5)) + '</td>' +
              '<td>' + esc(r.date) + '</td><td>' + esc(r.slot) + '</td>' +
              '<td>' + esc(r.name) + '</td><td>' + esc(r.jobTitle || '—') + '</td>' +
              '<td>' + esc(r.workType) + '</td><td>' + esc(r.projectCode || '—') + '</td>' +
              '<td class="num">' + r.rdHours + '</td><td class="num">' + r.nrdHours + '</td>' +
              '<td class="left" style="white-space:normal;max-width:280px">' + esc(r.content) + '</td></tr>';
          }).join('') + '</tbody></table></div>' +
          '<div class="card-title" style="font-size:13px;margin:16px 0 6px">按人汇总</div>' +
          '<div class="tbl-wrap"><table><thead><tr><th>姓名</th><th>研发工时</th><th>非研发工时</th>' +
            '<th>合计</th><th>半天数</th></tr></thead><tbody>' +
          d.byPerson.map(function (p) {
            return '<tr><td>' + esc(p.name) + '</td><td class="num">' + p.rd + '</td>' +
              '<td class="num">' + p.nrd + '</td><td class="num">' + (p.rd + p.nrd) + '</td>' +
              '<td class="num">' + p.units + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }).catch(function (e) {
        btn.disabled = false;
        toast(e.message, 'err');
      });
    };

    $('#exDownload').onclick = function () {
      window.location.href = '/api/admin/export/raw' + buildQuery(S.exportFormat || 'xlsx');
      toast('正在生成导出文件…');
    };
  }

  /* ============================ ⑥ 项目库 ============================ */
  function viewProjects() {
    setView('<div class="empty">加载中…</div>');
    api('/api/admin/projects').then(function (j) {
      var list = j.projects || [];
      S.projects = list;
      var html = '<div class="card">' +
        '<div class="card-head">' +
          '<div class="card-title">研发项目库 <small>共 ' + list.length + ' 个，启用 ' +
            list.filter(function (p) { return p.active; }).length + ' 个</small></div>' +
          '<div class="row">' +
            '<button class="btn sm" id="pjImport">批量导入</button>' +
            '<button class="btn sm primary" id="pjNew">＋ 新增项目</button>' +
          '</div>' +
        '</div>' +
        (list.length ? '<div class="tbl-wrap"><table><thead><tr>' +
          '<th>项目编号</th><th class="left">项目名称</th><th>类型</th><th>状态</th><th>操作</th>' +
          '</tr></thead><tbody>' + list.map(function (p) {
            return '<tr><td>' + esc(p.code) + '</td><td class="left">' + esc(p.name) + '</td>' +
              '<td>' + esc(p.type) + '</td>' +
              '<td>' + (p.active ? '<span class="tag green">启用</span>' : '<span class="tag">停用</span>') + '</td>' +
              '<td><button class="btn sm" data-edit="' + p.id + '">编辑</button> ' +
              '<button class="btn sm ' + (p.active ? 'danger' : '') + '" data-tog="' + p.id +
              '" data-active="' + (p.active ? 0 : 1) + '">' + (p.active ? '停用' : '启用') + '</button></td></tr>';
          }).join('') + '</tbody></table></div>'
          : '<div class="empty">还没有项目，点「批量导入」从 Excel 粘贴，或「新增项目」</div>') +
        '</div>';
      setView(html);

      $('#pjNew').onclick = function () { projectModal(null); };
      $('#pjImport').onclick = importProjectsModal;
      $$('[data-edit]').forEach(function (b) {
        b.onclick = function () {
          var p = list.filter(function (x) { return String(x.id) === b.getAttribute('data-edit'); })[0];
          projectModal(p);
        };
      });
      $$('[data-tog]').forEach(function (b) {
        b.onclick = function () {
          api('/api/admin/project/toggle', {
            body: { id: +b.getAttribute('data-tog'), active: b.getAttribute('data-active') === '1' }
          }).then(function () { toast('已更新', 'ok'); viewProjects(); })
            .catch(function (e) { toast(e.message, 'err'); });
        };
      });
    });
  }

  function projectModal(p) {
    var isNew = !p;
    modal({
      title: isNew ? '新增项目' : '编辑项目',
      lockable: true,
      body:
        '<div class="field"><label>项目编号</label>' +
          '<input id="pmCode" value="' + esc(p ? p.code : '') + '" placeholder="留空自动生成，如 RD-2026-04"></div>' +
        '<div class="field"><label>项目名称 <span style="color:#F54A45">*</span></label>' +
          '<input id="pmName" value="' + esc(p ? p.name : '') + '" placeholder="如 控制器固件优化"></div>' +
        '<div class="field"><label>类型</label><select id="pmType">' +
          '<option value="研发"' + (p && p.type === '研发' ? ' selected' : '') + '>研发</option>' +
          '<option value="非研发"' + (p && p.type === '非研发' ? ' selected' : '') + '>非研发</option>' +
        '</select></div>' +
        '<div class="field"><label>备注</label><input id="pmRemark" value="' + esc(p ? p.remark : '') + '"></div>',
      onOk: function () {
        var body = {
          id: p ? p.id : undefined,
          code: $('#pmCode').value.trim(),
          name: $('#pmName').value.trim(),
          type: $('#pmType').value,
          remark: $('#pmRemark').value.trim()
        };
        if (!body.name) { toast('请填写项目名称', 'err'); return false; }
        api('/api/admin/project/save', { body: body })
          .then(function () { toast('已保存', 'ok'); viewProjects(); })
          .catch(function (e) { toast(e.message, 'err'); });
      }
    });
  }

  function importProjectsModal() {
    modal({
      title: '批量导入项目',
      lockable: true,
      okText: '开始导入',
      body:
        '<div class="notice info">在 Excel 里选中「项目编号」和「项目名称」两列，Ctrl+C 复制后粘贴到下面。' +
        '只写名称也行，系统会自动编号。表头会自动跳过。</div>' +
        '<div class="field"><textarea id="ipText" rows="8" placeholder="RD-2026-01&#9;控制器固件优化&#10;RD-2026-02&#9;低功耗通信协议&#10;电源模块热设计"></textarea></div>' +
        '<div class="field"><label>或上传 Excel / CSV 文件</label>' +
        '<input type="file" id="ipFile" accept=".xlsx,.xlsm,.csv,.txt"></div>',
      onOk: function () {
        function done(d) {
          toast('新增 ' + d.created + ' 个，更新 ' + d.updated + ' 个，未变化 ' + d.skipped + ' 个', 'ok');
          if (d.errors && d.errors.length) {
            toast('有 ' + d.errors.length + ' 行未导入：' + d.errors[0].message, 'err');
          }
          $('#modalHost').innerHTML = '';
          viewProjects();
        }
        var file = $('#ipFile').files[0];
        if (file) {
          api('/api/admin/project/import-file?filename=' + encodeURIComponent(file.name),
            { method: 'POST', body: file })
            .then(function (j) { done(j.data); })
            .catch(function (e) { toast(e.message, 'err'); });
          return false;
        }
        var text = $('#ipText').value;
        if (!text.trim()) { toast('请粘贴内容或选择文件', 'err'); return false; }
        api('/api/admin/project/import', { body: { text: text } })
          .then(function (j) { done(j.data); })
          .catch(function (e) { toast(e.message, 'err'); });
        return false;
      }
    });
  }

  /* ============================ ⑦ 人员管理 ============================ */
  function viewUsers() {
    setView('<div class="empty">加载中…</div>');
    api('/api/admin/users').then(function (j) {
      var list = j.users || [];
      var html = '<div class="card">' +
        '<div class="card-head">' +
          '<div class="card-title">人员管理 <small>共 ' + list.length + ' 人</small></div>' +
          '<div class="row">' +
            '<button class="btn sm" id="usImport">批量导入</button>' +
            '<button class="btn sm primary" id="usNew">＋ 新增人员</button>' +
          '</div>' +
        '</div>' +
        '<div class="tbl-wrap"><table><thead><tr>' +
          '<th>姓名</th><th>账号</th><th>人员性质</th><th>岗位</th><th>部门</th><th>角色</th>' +
          '<th>每周应填</th><th>计入统计</th><th>状态</th><th>操作</th>' +
        '</tr></thead><tbody>' + list.map(function (u) {
          var aux = u.personType === '辅助人员';
          return '<tr><td>' + esc(u.name) + '</td><td class="muted">' + esc(u.username) + '</td>' +
            '<td>' + (aux ? '<span class="tag orange">辅助人员</span>'
                          : '<span class="tag blue">研发人员</span>') + '</td>' +
            '<td>' + (u.jobTitle ? esc(u.jobTitle) : '<span class="tag orange">未填</span>') + '</td>' +
            '<td>' + esc(u.dept || '—') + '</td>' +
            '<td>' + (u.role === 'admin' ? '<span class="tag green">管理员</span>' : '普通成员') + '</td>' +
            '<td class="num">' + u.weekQuota + '</td>' +
            '<td>' + (u.trackHours ? '是' : '否') + '</td>' +
            '<td>' + (u.active ? '<span class="tag green">启用</span>' : '<span class="tag">停用</span>') + '</td>' +
            '<td><button class="btn sm" data-uedit="' + u.id + '">编辑</button> ' +
            '<button class="btn sm" data-upwd="' + u.id + '">重置密码</button></td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<div class="muted" style="margin-top:12px">提示：' +
        '<b>研发人员</b>逐日填研发/非研发；<b>辅助人员</b>每个工作日自动预填「非研发 8 小时 · 部门行政管理事务」，仍可手动改。' +
        '「岗位」会直接出现在月度报表的岗位列；「计入统计」为否的人（如考勤管理员本人）不会出现在报表里。</div></div>';
      setView(html);

      $('#usNew').onclick = function () { userModal(null); };
      $('#usImport').onclick = importUsersModal;
      $$('[data-uedit]').forEach(function (b) {
        b.onclick = function () {
          var u = list.filter(function (x) { return String(x.id) === b.getAttribute('data-uedit'); })[0];
          userModal(u);
        };
      });
      $$('[data-upwd]').forEach(function (b) {
        b.onclick = function () {
          var pwd = prompt('输入新的初始密码（至少 6 位）', '123456');
          if (!pwd) return;
          api('/api/admin/user/reset', { body: { id: +b.getAttribute('data-upwd'), password: pwd } })
            .then(function () { toast('密码已重置，下次登录需修改', 'ok'); })
            .catch(function (e) { toast(e.message, 'err'); });
        };
      });
    });
  }

  function userModal(u) {
    var isNew = !u;
    modal({
      title: isNew ? '新增人员' : '编辑人员',
      lockable: true,
      body:
        '<div class="field"><label>姓名 <span style="color:#F54A45">*</span></label>' +
          '<input id="umName" value="' + esc(u ? u.name : '') + '"></div>' +
        '<div class="field"><label>登录账号 <span style="color:#F54A45">*</span></label>' +
          '<input id="umUser" value="' + esc(u ? u.username : '') + '" placeholder="建议用姓名拼音，如 lina"></div>' +
        (isNew ? '<div class="field"><label>初始密码</label>' +
          '<input id="umPwd" value="123456" placeholder="至少 6 位，首次登录会要求修改"></div>' : '') +
        '<div class="field"><label>人员性质 <span style="color:#F54A45">*</span></label>' +
          '<select id="umPtype">' +
            '<option value="研发人员"' + (!u || u.personType !== '辅助人员' ? ' selected' : '') +
              '>研发人员（逐日自己填研发/非研发）</option>' +
            '<option value="辅助人员"' + (u && u.personType === '辅助人员' ? ' selected' : '') +
              '>辅助人员（每天自动预填 非研发 8 小时）</option>' +
          '</select>' +
          '<div class="muted" style="margin-top:4px;font-size:12px">' +
            '选「辅助人员」后，每个工作日会自动填好「非研发 8 小时 · ' +
            '部门行政管理事务」，本人仍可手动修改；周末仍按休假处理。' +
          '</div></div>' +
        '<div class="field"><label>岗位</label>' +
          '<input id="umJob" value="' + esc(u ? u.jobTitle : '') + '" placeholder="如 嵌入式工程师 / 行政专员"></div>' +
        '<div class="field"><label>部门</label><input id="umDept" value="' + esc(u ? u.dept : '') + '"></div>' +
        '<div class="field"><label>账号权限</label><select id="umRole">' +
          '<option value="member"' + (u && u.role === 'member' ? ' selected' : '') + '>普通成员</option>' +
          '<option value="admin"' + (u && u.role === 'admin' ? ' selected' : '') + '>管理员</option>' +
        '</select></div>' +
        '<div class="field"><label>每周应填半天数</label>' +
          '<input id="umQuota" type="number" min="1" max="20" value="' + (u ? u.weekQuota : 10) + '"></div>' +
        '<div class="field"><label>选项</label>' +
          '<label class="radio"><input type="checkbox" id="umActive" ' + (!u || u.active ? 'checked' : '') + '> 启用</label>' +
          '<label class="radio"><input type="checkbox" id="umTrack" ' + (!u || u.trackHours ? 'checked' : '') + '> 计入工时统计</label>' +
        '</div>',
      onOk: function () {
        var body = {
          id: u ? u.id : undefined,
          name: $('#umName').value.trim(),
          username: $('#umUser').value.trim(),
          jobTitle: $('#umJob').value.trim(),
          dept: $('#umDept').value.trim(),
          personType: $('#umPtype').value,
          role: $('#umRole').value,
          weekQuota: +$('#umQuota').value || 10,
          active: $('#umActive').checked,
          trackHours: $('#umTrack').checked
        };
        if (isNew) body.password = $('#umPwd').value;
        if (!body.name) { toast('请填写姓名', 'err'); return false; }
        if (!body.username) { toast('请填写登录账号', 'err'); return false; }
        api('/api/admin/user/save', { body: body })
          .then(function () { toast('已保存', 'ok'); viewUsers(); })
          .catch(function (e) { toast(e.message, 'err'); });
      }
    });
  }

  function importUsersModal() {
    modal({
      title: '批量导入人员',
      lockable: true,
      okText: '开始导入',
      body:
        '<div class="notice info">每行一个：<b>账号 &nbsp;姓名 &nbsp;岗位 &nbsp;部门</b>（Tab 或逗号分隔）。' +
        '初始密码统一 123456，首次登录会要求修改。</div>' +
        '<div class="field"><textarea id="iuText" rows="8" placeholder="lina&#9;李娜&#9;嵌入式工程师&#9;技术中心&#10;wangqiang&#9;王强&#9;硬件工程师&#9;技术中心"></textarea></div>',
      onOk: function () {
        var text = $('#iuText').value;
        if (!text.trim()) { toast('请粘贴人员名单', 'err'); return false; }
        api('/api/admin/user/import', { body: { text: text } }).then(function (j) {
          toast('新增 ' + j.data.created + ' 人，更新 ' + j.data.updated + ' 人', 'ok');
          $('#modalHost').innerHTML = '';
          viewUsers();
        }).catch(function (e) { toast(e.message, 'err'); });
        return false;
      }
    });
  }

  /* ============================ ⑧ 填报监控 ============================ */
  function viewMonitor(periodStart) {
    setView('<div class="empty">加载中…</div>');
    var ps = periodStart || S.periodStart || todayStr();
    api('/api/admin/period-status?periodStart=' + ps).then(function (j) {
      var d = j.data;
      S.periodStart = d.periodStart;
      var html = '<div class="card">' +
        '<div class="card-head">' +
          '<div class="card-title">填报监控 <small>' + esc(d.periodLabel) +
            '（' + d.periodDays + ' 天）</small></div>' +
          '<div class="row">' +
            '<button class="btn sm" id="moPrev">← 上一期</button>' +
            '<button class="btn sm" id="moThis">本周</button>' +
            '<button class="btn sm" id="moNext">下一期 →</button>' +
            '<button class="btn sm primary" id="moRemind">催办未填人员</button>' +
          '</div>' +
        '</div>' +
        '<div class="stats">' +
          stat('应填人数', d.total + '<small>人</small>') +
          stat('已提交', d.submittedCount + '<small>人</small>') +
          stat('完全未填', d.missingCount + '<small>人</small>') +
          stat('填了未交', d.incompleteCount + '<small>人</small>') +
        '</div>' +
        '<div class="tbl-wrap"><table><thead><tr>' +
          '<th>姓名</th><th>岗位</th><th>已填/应填</th><th>填报率</th><th>状态</th>' +
        '</tr></thead><tbody>' + d.rows.map(function (r) {
          var tag = r.submitted ? '<span class="tag green">已提交</span>'
            : r.missing ? '<span class="tag red">未填</span>'
              : r.incomplete ? '<span class="tag orange">未填满</span>'
                : '<span class="tag blue">待提交</span>';
          return '<tr><td>' + esc(r.name) + '</td><td>' + esc(r.jobTitle || '—') + '</td>' +
            '<td class="num">' + r.filled + '/' + r.quota + '</td>' +
            '<td class="num">' + r.rate + '%</td><td>' + tag + '</td></tr>';
        }).join('') + '</tbody></table></div></div>';
      setView(html);

      $('#moPrev').onclick = function () { viewMonitor(addDays(parseYmd(d.periodStart), -1) && fmtDate(addDays(parseYmd(d.periodStart), -1))); };
      $('#moNext').onclick = function () { viewMonitor(fmtDate(addDays(parseYmd(d.periodEnd), 1))); };
      $('#moThis').onclick = function () { viewMonitor(todayStr()); };
      $('#moRemind').onclick = function () {
        var btn = this; btn.disabled = true;
        api('/api/admin/missing?periodStart=' + d.periodStart).then(function (j) {
          var m = j.data;
          btn.disabled = false;
          if (!m.count) { toast('本周期所有人都已提交', 'ok'); return; }
          modal({
            title: '催办：' + m.count + ' 人未完成',
            lockable: true,
            okText: '推送到飞书群',
            body: '<div class="field"><label>未完成名单</label>' +
              '<div style="background:#F7F8FA;border-radius:8px;padding:10px 12px;font-size:13px;line-height:1.7">' +
              m.members.map(function (x) {
                return esc(x.name) + '（' + (x.missing ? '未填' : (x.filled + '/' + x.quota)) + '）';
              }).join('、') + '</div></div>' +
              '<div class="muted">推送需要在「设置」里配置飞书群机器人 Webhook。</div>',
            onOk: function () {
              api('/api/admin/remind', { body: { periodStart: d.periodStart } }).then(function (r) {
                toast(r.data.message || '已推送', r.ok ? 'ok' : 'err');
              }).catch(function (e) { toast(e.message, 'err'); });
            }
          });
        }).catch(function (e) { btn.disabled = false; toast(e.message, 'err'); });
      };
    }).catch(function (e) { setView('<div class="empty">' + esc(e.message) + '</div>'); });
  }

  /* ============================ ⑨ 设置 ============================ */
  function viewSettings() {
    setView('<div class="empty">加载中…</div>');
    api('/api/admin/settings').catch(function () { return { data: null }; }).then(function (res) {
      var st = res.data;
      S.settings = st;
      var info = (st && st.serverInfo) || {};
      var html = '';

      if (S.user.mustChangePwd) {
        html += '<div class="notice">你正在使用初始密码，请立即修改后再使用系统。</div>';
      }

      html += '<div class="card"><div class="card-head"><div class="card-title">修改密码</div></div>' +
        '<div class="field"><label>原密码</label><input type="password" id="pwOld"></div>' +
        '<div class="field"><label>新密码（至少 6 位）</label><input type="password" id="pwNew"></div>' +
        '<div class="field"><label>确认新密码</label><input type="password" id="pwNew2"></div>' +
        '<button class="btn primary" id="pwSave">保存新密码</button></div>';

      if (S.user.isAdmin && st) {
        html += '<div class="card"><div class="card-head"><div class="card-title">飞书群提醒（可选）</div></div>' +
          '<div class="notice info">在飞书群里「添加机器人 → 自定义机器人」，把 Webhook 地址填到这里，' +
          '系统就能把未填报人员名单推到群里。本机只需能访问外网，不需要公网 IP。</div>' +
          '<div class="field"><label>Webhook 地址</label>' +
          '<input id="stHook" value="' + esc(st.feishuWebhook || '') + '" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx"></div>' +
          '<div class="field"><label>定时提醒（每周）</label>' +
          '<div class="row">' +
            '<select id="stWd" class="mini-input">' +
            ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map(function (w, i) {
              return '<option value="' + i + '"' + (i === st.remindWeekday ? ' selected' : '') + '>' + w + '</option>';
            }).join('') + '</select>' +
            '<input id="stHour" type="number" min="0" max="23" value="' + st.remindHour + '" class="mini-input" style="width:80px"> 点' +
            '<label class="radio"><input type="checkbox" id="stRemind" ' + (st.remindEnabled ? 'checked' : '') + '> 开启</label>' +
          '</div></div>' +
          '<div class="row"><button class="btn primary" id="stSave">保存设置</button>' +
          '<button class="btn" id="stTest">发送测试消息</button></div></div>';

        html += '<div class="card"><div class="card-head"><div class="card-title">服务器信息</div>' +
          '<button class="btn sm" id="bkBtn">下载数据库备份</button></div>' +
          '<div class="tbl-wrap"><table><tbody>' +
          row2('访问地址', (info.lanAddresses || []).join('   ') || '未检测到局域网 IP') +
          row2('服务端口', info.port) +
          row2('半天折算', info.halfDayHours + ' 小时/半天') +
          row2('每周应填', info.weekQuota + ' 个半天') +
          row2('强制填满', info.enforceFullWeek ? '是' : '否') +
          row2('跨周合并', '月末/月初 ≤3 天的零碎片段自动并入相邻周期') +
          row2('数据库', info.dbPath) +
          row2('报表目录', info.outputDir) +
          '</tbody></table></div>' +
          '<div class="muted" style="margin-top:10px">建议每周点一次「下载数据库备份」，' +
          '把文件另存到U盘或网盘。</div></div>';
      }

      setView(html);

      $('#pwSave').onclick = function () {
        var o = $('#pwOld').value, n = $('#pwNew').value, n2 = $('#pwNew2').value;
        if (!o) { toast('请输入原密码', 'err'); return; }
        if (n.length < 6) { toast('新密码至少 6 位', 'err'); return; }
        if (n !== n2) { toast('两次输入的新密码不一致', 'err'); return; }
        api('/api/password', { body: { oldPassword: o, newPassword: n } }).then(function () {
          toast('密码已修改', 'ok');
          S.user.mustChangePwd = false;
          viewSettings();
        }).catch(function (e) { toast(e.message, 'err'); });
      };

      if ($('#stSave')) {
        $('#stSave').onclick = function () {
          api('/api/admin/settings', {
            body: {
              feishuWebhook: $('#stHook').value.trim(),
              remindWeekday: +$('#stWd').value,
              remindHour: +$('#stHour').value || 17,
              remindEnabled: $('#stRemind').checked
            }
          }).then(function () { toast('设置已保存', 'ok'); }).catch(function (e) { toast(e.message, 'err'); });
        };
        $('#stTest').onclick = function () {
          var btn = this; btn.disabled = true;
          api('/api/admin/settings', { body: { feishuWebhook: $('#stHook').value.trim() } })
            .then(function () { return api('/api/admin/test-webhook', { body: {} }); })
            .then(function (j) { toast(j.data.message, j.ok ? 'ok' : 'err'); })
            .catch(function (e) { toast(e.message, 'err'); })
            .then(function () { btn.disabled = false; });
        };
        $('#bkBtn').onclick = function () {
          window.location.href = '/api/admin/backup';
        };
      }

      function row2(k, v) {
        return '<tr><td class="left" style="width:120px;color:var(--text2)">' + esc(k) + '</td>' +
          '<td class="left">' + esc(v == null ? '' : String(v)) + '</td></tr>';
      }
    });
  }

  /* ============================ 启动 ============================ */
  function boot() {
    /* 先取服务端口径（工资月起始日），避免按自然月算错当前月 */
    api('/api/ping').then(function (j) {
      if (j && j.monthCycleStartDay) CYCLE.startDay = j.monthCycleStartDay;
    }).catch(function () {});

    $('#loginForm').onsubmit = function (e) {
      e.preventDefault();
      var btn = $('#lgBtn'); btn.disabled = true; $('#lgErr').textContent = '';
      doLogin($('#lgUser').value.trim(), $('#lgPwd').value)
        .then(function () { btn.disabled = false; enterApp(); })
        .catch(function (err) {
          btn.disabled = false;
          $('#lgErr').textContent = err.message || '登录失败';
        });
    };

    $('#btnLogout').onclick = function () {
      api('/api/logout', { method: 'POST', body: {} }).catch(function () {});
      logoutLocal();
    };

    if (S.token) {
      api('/api/me').then(function (j) { S.user = j.user; enterApp(); })
        .catch(function () { logoutLocal(); });
    }

    var qs = new URLSearchParams(location.search);
    if (qs.get('period')) S.periodStart = qs.get('period');
    if (qs.get('week')) S.periodStart = qs.get('week');
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
