# -*- coding: utf-8 -*-
"""
启动前诊断工具（v1.3）
==========================================================
双击「工具\诊断启动问题.bat」或在命令行执行：
    python 诊断.py

它会逐项检查启动必需的环节，并直接告诉你是哪一步导致起不来。
"""
import os
import socket
import sys
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
# 先挂上自带的 vendor，否则「没装 openpyxl」的电脑会误报缺组件
_VENDOR = os.path.join(BASE, 'vendor')
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

OK = '[OK]  '
BAD = '[失败]'
WARN = '[注意]'


def line(tag, msg, detail=''):
    print('%s %s%s' % (tag, msg, ('  -> ' + str(detail)) if detail else ''))


def _port_free(port):
    """
    判断端口是否可被本程序独占使用。
    先尝试 bind（不带 SO_REUSEADDR），再用 connect 二次确认：
    有进程在监听时 connect 会成功 => 端口被占用。
    """
    # 1) 尝试绑定
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', port))
    except OSError as e:
        s.close()
        return False, (e.strerror or str(e))
    s.close()

    # 2) 二次确认：能连上说明已有服务在监听
    c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c.settimeout(0.4)
    try:
        c.connect(('127.0.0.1', port))
        c.close()
        return False, '已有程序在监听该端口'
    except (ConnectionRefusedError, socket.timeout, OSError):
        c.close()
        return True, ''


def main():
    print('=' * 64)
    print('  研发工时统计系统 · 启动诊断')
    print('=' * 64)

    # 1. Python 版本
    v = sys.version_info
    if v >= (3, 9):
        line(OK, 'Python 版本 %d.%d.%d' % (v[0], v[1], v[2]))
    else:
        line(BAD, 'Python 版本过低：%d.%d.%d，需要 3.9+'
                  % (v[0], v[1], v[2]))
    print('       解释器：%s' % sys.executable)

    # 2. 依赖：openpyxl（项目已内置 vendor）
    try:
        import openpyxl
        line(OK, 'openpyxl 可用（%s）' % getattr(openpyxl, '__version__', '?'))
    except Exception as e:
        line(BAD, 'openpyxl 导入失败', e)
        print('       请确认 vendor/ 目录完整（这是项目自带的，不需要 pip 安装）')

    # 3. 目录写权限
    for name in ('data', '输出', '备份'):
        d = os.path.join(BASE, name)
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, '_probe.tmp')
            with open(probe, 'w') as f:
                f.write('x')
            os.remove(probe)
            line(OK, '目录可写：%s' % name)
        except Exception as e:
            line(BAD, '目录不可写：%s' % name, e)

    # 4. 配置文件能否导入
    try:
        from app import config
        line(OK, '配置加载成功，端口=%d' % config.PORT)
    except Exception as e:
        line(BAD, '配置加载失败（app/config.py 可能有语法错误）', e)
        return

    # 5. 端口占用检查（重点）
    #    注意：绝对不能用 SO_REUSEADDR —— Windows 上它允许重复绑定，
    #    会把"已被占用"误判成"可用"。
    port = config.PORT
    free, reason = _port_free(port)
    if free:
        line(OK, '端口 %d 可用' % port)
    else:
        line(BAD, '端口 %d 已被占用' % port, reason)
        print('       解决办法：见本窗口后面的建议')
    if not free:
        print()
        print('       >>> 端口冲突的处理办法（按推荐顺序）')
        print('       A. 让它自动换端口：把 app/config.py 里的')
        print('          PORT = %d   改成   PORT = 0' % port)
        print('          （0 表示自动挑一个空闲端口，启动窗口会打印实际地址）')
        print('       B. 直接换一个固定端口：把 PORT 改成 8080 或 9000，')
        print('          同时把「工具\\允许局域网访问(防火墙).bat」里的端口也改掉')
        print('       C. 找到占用者并关掉：')
        print('          netstat -ano | findstr :%d' % port)
        print('          记下最后一列的 PID，然后：taskkill /f /pid <PID>')

    # 6. 数据库
    if os.path.exists(config.DB_PATH):
        try:
            con = sqlite3.connect(config.DB_PATH)
            cols = [r[1] for r in con.execute('PRAGMA table_info(entries)').fetchall()]
            con.close()
            miss = [c for c in ('hours', 'seq', 'work_kind', 'period_start')
                    if cols and c not in cols]
            if miss:
                line(WARN, '数据库是旧版结构，缺少列：%s' % miss)
                print('       启动时会自动升级；若报错可先备份后删除 data/timesheet.db')
            else:
                line(OK, '数据库结构正常：%s' % config.DB_PATH)
        except Exception as e:
            line(BAD, '数据库文件无法打开（可能损坏或被占用）', e)
            print('       可先改名备份：把 data/timesheet.db 改成 timesheet.db.bak 再启动')
    else:
        line(OK, '尚无数据库文件，首次启动会新建')

    # 7. 局域网 IP
    print()
    try:
        from app import api
        urls = api._lan_addresses()
        if urls:
            line(OK, '可用的局域网地址：%s' % '   '.join(urls))
        else:
            line(WARN, '没检测到局域网 IP（可能没联网，仅本机可用）')
    except Exception as e:
        line(WARN, '无法检测局域网地址', e)

    print()
    print('=' * 64)
    if free:
        print('  结论：没有发现阻塞启动的问题，可以正常双击「启动服务.bat」')
    else:
        print('  结论：端口 %d 被占用，请按上面 A / B / C 处理' % port)
    print('=' * 64)
    print()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
    input('按回车键退出...')
