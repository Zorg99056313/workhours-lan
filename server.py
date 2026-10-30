# -*- coding: utf-8 -*-
"""
研发工时统计系统 · 局域网服务端
==========================================================
用法：双击「启动服务.bat」，或在本目录执行
    python server.py
然后用浏览器打开提示的地址即可。关闭窗口即停止服务。
"""
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from app import api, auth, config, db, httpd, notify, service  # noqa: E402


# ---------------------------------------------------------------- 定时提醒
_last_remind_day = {'v': None}


def _remind_scheduler():
    """后台线程：到点把未填报人员推到飞书群"""
    while True:
        try:
            time.sleep(30)
            enabled = (db.get_setting('remind_enabled') or str(config.REMIND_ENABLED)) == 'True'
            if not enabled:
                continue
            wd = int(db.get_setting('remind_weekday') or config.REMIND_WEEKDAY)
            hh = int(db.get_setting('remind_hour') or config.REMIND_HOUR)
            now = datetime.now()
            today = date.today().isoformat()
            if now.weekday() != wd or now.hour != hh:
                continue
            if _last_remind_day['v'] == today:
                continue
            _last_remind_day['v'] = today

            data = service.missing_members()
            if data['count'] == 0:
                httpd._log('定时提醒：所有人都已提交，跳过')
                continue
            urls = api._lan_addresses()
            text = notify.build_remind_text(data, urls[0] if urls else '')
            ok, msg = notify.send_text(text)
            httpd._log('定时提醒：%d 人未完成，飞书推送%s（%s）'
                       % (data['count'], '成功' if ok else '失败', msg))
        except Exception as e:
            httpd._log('定时提醒线程异常：%s' % e)


def _candidates():
    """要尝试的端口列表：config.PORT 在首位，其后是常用备用端口"""
    base = config.PORT
    cands = [base]
    for p in (8000, 8080, 8001, 8888, 9000, 0):
        if p not in cands:
            cands.append(p)
    return cands


def _serve_with_fallback():
    """依次尝试端口；0 表示让系统自动分配一个空闲端口"""
    tried = []
    last_err = None
    for port in _candidates():
        tried.append(port)
        config.PORT = port
        try:
            srv = httpd.serve()
            if port == 0:
                # 系统分配的端口
                real = srv.server_address[1]
                config.PORT = real
            return srv, config.PORT, {'tried': [p for p in tried if p]}
        except OSError as e:
            last_err = e
            continue
    return None, None, {'tried': [p for p in tried if p], 'error': last_err}


def banner(httpd_srv):
    urls = api._lan_addresses()
    local = 'http://127.0.0.1:%d' % config.PORT
    line = '=' * 62
    print()
    print(line)
    print('  %s  已启动' % config.SERVER_NAME)
    print(line)
    print('  本机访问：  %s' % local)
    if urls:
        print('  同事访问：  %s' % '   '.join(urls))
        print('              （同一局域网/公司 WiFi 下的电脑和手机都能打开）')
    else:
        print('  同事访问：  未检测到局域网 IP，请检查网络连接')
    print()
    print('  登录账号：  %s' % config.ADMIN_DEFAULT_USERNAME)
    print('  初始密码：  %s   ← 登录后请立刻在「设置」里修改' % config.ADMIN_DEFAULT_PASSWORD)
    print()
    print('  数据文件：  %s' % config.DB_PATH)
    print('  报表输出：  %s' % config.OUTPUT_DIR)
    print()
    print('  停止服务：  在这个窗口按 Ctrl+C，或直接关闭窗口')
    print(line)
    print()
    sys.stdout.flush()


def main():
    db.init_db()
    auth.cleanup_sessions()

    wanted_port = config.PORT          # 记住原始配置端口
    srv, used_port, note = _serve_with_fallback()
    if srv is None:
        print()
        print('!! 启动失败：端口 %s 都无法使用。' % '/' .join(str(p) for p in note['tried']))
        print('   可能原因：端口被占用，或被安全软件拦截。')
        print('   解决办法：')
        print('     1) 运行「工具\\诊断启动问题.bat」查看具体原因')
        print('     2) 打开 app/config.py，把 PORT 改成 0（自动选空闲端口）')
        print('        或改成 8080 / 9000，再重新启动')
        print()
        input('按回车键退出...')
        return 1
    if wanted_port and used_port != wanted_port:
        print()
        print('!! 注意：原端口 %d 不可用（被占用），已自动改用 %d。'
              % (wanted_port, used_port))
        print('   请把下面的新地址发给同事；想固定下来就把 app/config.py 的'
              ' PORT 改成 %d。' % used_port)
    banner(srv)

    threading.Thread(target=_remind_scheduler, daemon=True).start()

    if config.AUTO_OPEN_BROWSER:
        # 注意：必须用实际监听端口 used_port，而不是 config.PORT ——
        # 发生过端口回退时，config.PORT 是打不开的。
        threading.Timer(1.0, lambda: webbrowser.open(
            'http://127.0.0.1:%d' % used_port)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n正在停止服务...')
    finally:
        try:
            srv.server_close()
        except Exception:
            pass
        print('服务已停止。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
