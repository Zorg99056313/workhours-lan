# -*- coding: utf-8 -*-
"""卸载：先自动备份数据，再清理快捷方式/注册表，最后删除程序文件夹。

由「卸载.bat」调用。设计原则：
  * 绝不悄悄删数据 —— 先把 data / 输出 复制到桌面；
  * 删不掉就老实说，让用户手动删；
  * 不碰任何与本事无关的注册表项。
"""
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

APP_NAME = '研发工时统计系统'
RUN_KEY = 'WorkHoursServer'
RULE = 'WorkHoursServer'
UNINST_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\WorkHoursServer'


def pause(msg='按回车键退出...'):
    try:
        input(msg)
    except EOFError:
        pass


def say(s=''):
    print(s)


def desktop_dir():
    d = os.path.join(os.environ.get('USERPROFILE', BASE), 'Desktop')
    if os.path.isdir(d):
        return d
    d2 = os.path.join(os.environ.get('USERPROFILE', BASE), '桌面')
    return d2 if os.path.isdir(d2) else BASE


def backup_data():
    """把 data 和 输出 复制到桌面，返回备份目录（没有数据时返回 None）"""
    has_data = os.path.isdir(os.path.join(BASE, 'data')) and os.listdir(
        os.path.join(BASE, 'data'))
    has_out = os.path.isdir(os.path.join(BASE, '输出')) and os.listdir(
        os.path.join(BASE, '输出'))
    if not has_data and not has_out:
        return None
    stamp = time.strftime('%Y%m%d_%H%M')
    dst = os.path.join(desktop_dir(), '%s_数据备份_%s' % (APP_NAME, stamp))
    os.makedirs(dst, exist_ok=True)
    n = 0
    for sub in ('data', '输出'):
        src = os.path.join(BASE, sub)
        if not os.path.isdir(src):
            continue
        for fn in os.listdir(src):
            sp = os.path.join(src, fn)
            if os.path.isfile(sp):
                shutil.copy2(sp, os.path.join(dst, fn))
                n += 1
    return dst if n else None


def remove_registry():
    """删注册表项：开机自启 + 控制面板卸载入口"""
    try:
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r'Software\Microsoft\Windows\CurrentVersion\Run',
                               0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k, RUN_KEY)
            winreg.CloseKey(k)
            say('  [OK] 已取消开机自动启动')
        except FileNotFoundError:
            pass
        except OSError:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
            say('  [OK] 已移除"程序和功能"里的条目')
        except OSError:
            pass
    except Exception as e:
        say('  [跳过] 注册表清理：%s' % e)


def remove_shortcuts():
    paths = []
    for env in ('PUBLIC', 'USERPROFILE'):
        root = os.environ.get(env)
        if not root:
            continue
        paths.append(os.path.join(root, 'Desktop', APP_NAME + '.lnk'))
    pub = os.environ.get('PUBLIC')
    if pub:
        paths.append(os.path.join(pub, 'Desktop', APP_NAME + '.lnk'))
        paths.append(os.path.join(pub, 'Start Menu', 'Programs',
                                  APP_NAME, APP_NAME + '.lnk'))
        paths.append(os.path.join(pub, 'Start Menu', 'Programs',
                                  APP_NAME, '卸载 ' + APP_NAME + '.lnk'))
    user = os.environ.get('APPDATA')
    if user:
        paths.append(os.path.join(user, r'Microsoft\Windows\Start Menu\Programs',
                                  APP_NAME, APP_NAME + '.lnk'))
    removed = 0
    for p in set(paths):
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed += 1
        except Exception:
            pass
    # 删空的开始菜单文件夹
    pub = os.environ.get('PUBLIC')
    if pub:
        g = os.path.join(pub, 'Start Menu', 'Programs', APP_NAME)
        try:
            if os.path.isdir(g) and not os.listdir(g):
                os.rmdir(g)
        except Exception:
            pass
    say('  [OK] 已删除 %d 个快捷方式' % removed)


def remove_firewall():
    """需要管理员权限；没有权限就提示用户手动处理"""
    cmds = [
        ['netsh', 'advfirewall', 'firewall', 'delete', 'rule', 'name=' + RULE],
        ['netsh', 'advfirewall', 'firewall', 'delete', 'rule',
         'name=%s (port)' % RULE],
    ]
    ok = 0
    for c in cmds:
        try:
            r = subprocess.run(c, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=20)
            if r.returncode == 0:
                ok += 1
        except Exception:
            pass
    if ok:
        say('  [OK] 已移除防火墙规则')
    else:
        say('  [提示] 防火墙规则未移除（需要管理员权限）。')
        say('         如需彻底清理：以管理员身份运行')
        say('         netsh advfirewall firewall delete rule name=%s' % RULE)


def schedule_delete():
    """把自己所在文件夹删掉：等本进程退出后由 cmd 执行"""
    try:
        subprocess.Popen(
            'cmd /c timeout /t 3 /nobreak >nul & rmdir /s /q "%s"' % BASE,
            shell=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except Exception as e:
        say('  [!] 自动删除失败：%s' % e)
        return False


def main():
    say('')
    say('=' * 62)
    say('   %s  卸载' % APP_NAME)
    say('=' * 62)
    say('')
    say('  卸载会删除程序文件。工时数据会先自动备份到桌面。')
    say('  程序位置：%s' % BASE)
    say('')
    try:
        ans = input('  确定要卸载吗？输入 y 回车继续（直接回车取消）：').strip().lower()
    except EOFError:
        ans = ''
    if ans != 'y':
        say('')
        say('  已取消，什么都没动。')
        pause()
        return 0

    say('')
    say('[1/4] 备份数据 ...')
    bp = backup_data()
    if bp:
        say('  [OK] 已备份到：%s' % bp)
    else:
        say('  [跳过] 没有需要备份的数据')

    say('')
    say('[2/4] 清理快捷方式 ...')
    remove_shortcuts()

    say('')
    say('[3/4] 清理注册表 ...')
    remove_registry()

    say('')
    say('[4/4] 清理防火墙 ...')
    remove_firewall()

    say('')
    say('=' * 62)
    if bp:
        say('  卸载完成。数据已备份到：')
        say('    %s' % bp)
        say('  以后想恢复：把备份里的 timesheet.db 放回新装的 data 目录即可。')
    else:
        say('  卸载完成。')
    say('=' * 62)
    say('')
    say('  正在删除程序文件夹，本窗口会自动关闭...')
    if not schedule_delete():
        say('  请手动删除：%s' % BASE)
        pause()
    time.sleep(1.5)
    return 0


if __name__ == '__main__':
    sys.exit(main())
