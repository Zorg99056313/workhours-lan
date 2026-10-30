# -*- coding: utf-8 -*-
"""停止正在运行的工时统计服务（由 停止服务.bat / stop_server.bat 调用）

要点：
1. 只认「本地地址端口 == PORT 且状态 == LISTENING」的行，
   绝不要把 TCP 连接行（TIME_WAIT / ESTABLISHED，对端端口是 8000）当成服务进程，
   否则会去 kill PID 0 之类的系统进程，报「拒绝访问」。
2. Windows 下优先用 taskkill /F /PID（稳定、无需 psutil）；
   os.kill(pid, 9) 在 Windows 上等价于 TerminateProcess，
   缺句柄权限时会抛 PermissionError，只作为后备。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from app import config  # noqa: E402


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=20)
        return (r.returncode, (r.stdout or '') + (r.stderr or ''))
    except Exception:
        return (-1, '')


def find_pids_on_port(port):
    """找「监听」指定端口的进程 PID（不依赖 psutil）"""
    suffix = ':%d' % port
    pids = []
    _, out = _run(['netstat', '-ano'])
    for line in out.splitlines():
        parts = line.split()
        # 形如: TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  1234
        if len(parts) < 5:
            continue
        if parts[0].upper() not in ('TCP', 'TCPV6'):
            continue
        if not parts[1].endswith(suffix):        # 本地地址端口必须匹配
            continue
        if parts[3].upper() != 'LISTENING':       # 必须处于监听状态
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid > 0 and pid not in pids:           # 0 / 4 是系统伪进程，跳过
            pids.append(pid)
    return pids


def kill_pid(pid):
    """返回 (是否成功, 说明)"""
    if os.name == 'nt':
        code, out = _run(['taskkill', '/F', '/PID', str(pid)])
        if code == 0:
            return True, ''
        # 已经自己退出了，也算成功
        if 'not found' in out.lower() or '没有找到' in out:
            return True, '（进程已自行退出）'
        msg = out.strip().splitlines()[-1] if out.strip() else 'taskkill 失败'
        return False, msg
    try:
        os.kill(pid, 9)
        return True, ''
    except ProcessLookupError:
        return True, '（进程已自行退出）'
    except Exception as e:
        return False, str(e)


def main():
    port = config.PORT
    print()
    print('  正在查找占用端口 %d 的服务进程...' % port)
    pids = find_pids_on_port(port)

    if not pids:
        print()
        print('  没有发现正在运行的服务（可能已经关闭了）。')
        print('  提示：也可以直接在服务窗口按 Ctrl+C，或关闭那个黑窗口。')
        return 0

    stopped, failed = 0, []
    for pid in pids:
        ok, note = kill_pid(pid)
        if ok:
            print('  已结束进程 PID=%d %s' % (pid, note))
            stopped += 1
        else:
            print('  结束 PID=%d 失败：%s' % (pid, note))
            failed.append(pid)

    # 复查端口是否真的释放
    import time
    for _ in range(10):
        if not find_pids_on_port(port):
            break
        time.sleep(0.3)
    still = find_pids_on_port(port)

    print()
    if not still:
        print('  服务已停止，端口 %d 已释放。' % port)
    else:
        print('  端口 %d 仍被 PID=%s 占用。' % (port, ', '.join(str(p) for p in still)))
        print('  请打开「任务管理器」→ 详细信息 → 结束 python.exe 后重试。')
        print('  或用管理员身份运行：  taskkill /F /PID %d' % still[0])
    return 0 if not still else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('  出错：%s' % e)
        sys.exit(1)
