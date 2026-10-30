# -*- coding: utf-8 -*-
"""备份数据（由 工具\\备份数据.bat 调用）"""
import os
import shutil
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from app import config  # noqa: E402


def main():
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    print()
    print('  正在备份工时统计数据...')

    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    ok = False

    db_path = config.DB_PATH
    if os.path.exists(db_path):
        dst = os.path.join(config.BACKUP_DIR, 'timesheet_%s.db' % stamp)
        try:
            import sqlite3
            src = sqlite3.connect(db_path)
            out = sqlite3.connect(dst)
            try:
                src.backup(out)
            finally:
                out.close()
                src.close()
            size = os.path.getsize(dst)
            print('  [OK] 数据库已备份：备份\\timesheet_%s.db（%.1f KB）'
                  % (stamp, size / 1024.0))
            ok = True
        except Exception:
            try:
                shutil.copyfile(db_path, dst)
                print('  [OK] 数据库已复制：备份\\timesheet_%s.db' % stamp)
                ok = True
            except Exception as e:
                print('  [X] 备份失败：%s' % e)
                print('      数据库可能正在被服务占用，可先停止服务再试。')
    else:
        print('  [!] 还没有数据库文件（服务可能还没启动过）')

    # 报表也一起备份
    out_dir = config.OUTPUT_DIR
    if os.path.isdir(out_dir):
        n = 0
        for fn in os.listdir(out_dir):
            if fn.lower().endswith(('.xlsx', '.csv')):
                try:
                    shutil.copy2(os.path.join(out_dir, fn),
                                 os.path.join(config.BACKUP_DIR, fn))
                    n += 1
                except Exception:
                    pass
        if n:
            print('  [OK] 已同时复制 %d 个报表到 备份 目录' % n)

    print()
    print('  建议：每周做一次备份，把「备份」目录里的文件另存到 U 盘或公司网盘。')
    print('        换电脑时，把 data 和 输出 两个目录拷到新电脑同样的位置即可继续使用。')
    return 0 if ok else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
