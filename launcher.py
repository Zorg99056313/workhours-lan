# -*- coding: utf-8 -*-
"""
启动入口（由 启动服务.bat 调用）
==========================================================
为什么要有这个文件：
  cmd.exe 在 chcp 65001 下解析含中文的 .bat 会出错（字节错位），
  导致双击后窗口一闪就关、看起来"没有任何反应"。
  所以 .bat 只保留纯 ASCII，所有中文提示都放到这里由 Python 打印。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 重要：先把自己带的 vendor 挂上，再去 import openpyxl。
# 否则在「没装过 openpyxl」的电脑上，preflight 会误报「缺少 Excel 组件」。
_VENDOR = os.path.join(BASE, 'vendor')
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BAR = '=' * 62


def say(*lines):
    for ln in lines or ('',):
        print(ln)
    sys.stdout.flush()


def pause_quietly():
    try:
        input('按回车键关闭窗口...')
    except EOFError:
        pass


def preflight():
    """启动前自检，返回 (ok, 说明)"""
    v = sys.version_info
    if v < (3, 9):
        return False, ('Python 版本过低（当前 %d.%d.%d），需要 3.9 或更高。\n'
                       '       建议安装 Python 3.12：https://www.python.org/downloads/windows/'
                       % (v[0], v[1], v[2]))

    try:
        import openpyxl  # noqa: F401
    except Exception as e:
        return False, ('缺少 Excel 组件（openpyxl）。\n'
                       '       本系统自带该组件，请确认 vendor/ 目录完整没被删掉。\n'
                       '       详细错误：%s' % e)

    for d in ('data', '输出', '备份'):
        p = os.path.join(BASE, d)
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, '.probe')
            with open(probe, 'w') as f:
                f.write('x')
            os.remove(probe)
        except Exception as e:
            return False, ('目录无法写入：%s\n'
                           '       原因：%s\n'
                           '       解决办法：把整个程序文件夹放到 D 盘或"文档"下，'
                           '不要放在 C:\\Program Files。' % (p, e))

    try:
        from app import config  # noqa: F401
    except Exception as e:
        return False, ('配置文件 app/config.py 加载失败。\n'
                       '       可能被误改或编码被破坏。详细错误：%s' % e)

    return True, ''


def main():
    say('')
    say(BAR)
    say('            研发工时统计系统   正在启动...')
    say(BAR)

    say('')
    say('  [1/2] 检查运行环境 ...')
    ok, reason = preflight()
    if not ok:
        say('')
        say('  [!] 环境检查未通过：')
        say('       ' + reason)
        say('')
        say(BAR)
        say('  建议运行「工具\\诊断启动问题.bat」查看更详细的诊断结果')
        say(BAR)
        pause_quietly()
        return 1

    say('       Python %d.%d.%d   OK' % (sys.version_info[0],
                                        sys.version_info[1],
                                        sys.version_info[2]))
    say('       Excel 组件        OK')
    say('       数据目录          OK')

    say('')
    say('  [2/2] 启动服务（关闭本窗口即停止服务）...')
    say('')

    try:
        import server
        return server.main()
    except Exception as e:
        import traceback
        say('')
        say('  [!] 启动过程中出现异常：')
        traceback.print_exc()
        say('')
        say(BAR)
        say('  请把上面的报错内容截图，或运行「工具\\诊断启动问题.bat」')
        say(BAR)
        pause_quietly()
        return 1


if __name__ == '__main__':
    sys.exit(main())
