# -*- coding: utf-8 -*-
"""飞书群机器人提醒（可选功能，纯出网请求，不需要公网 IP）"""
import json
import urllib.error
import urllib.request

from . import config, db


def webhook_url():
    return (db.get_setting('feishu_webhook') or config.FEISHU_WEBHOOK or '').strip()


def send_text(text):
    """向飞书自定义机器人发一条文本消息，返回 (ok, message)"""
    url = webhook_url()
    if not url:
        return False, '还没有配置飞书群机器人 Webhook 地址'
    payload = {'msg_type': 'text', 'content': {'text': text}}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode('utf-8', 'replace')
        try:
            j = json.loads(body)
        except Exception:
            j = {}
        code = j.get('code', j.get('StatusCode', 0))
        if code not in (0, None):
            return False, '飞书返回错误：%s %s' % (code, j.get('msg') or body[:120])
        return True, '已发送'
    except urllib.error.HTTPError as e:
        return False, '发送失败（HTTP %s），请检查 Webhook 地址是否正确' % e.code
    except Exception as e:
        return False, '发送失败：%s（检查本机能否访问外网 open.feishu.cn）' % e


def build_remind_text(data, app_url=''):
    lines = ['【工时填报提醒】%s' % data['weekRange'],
             '还有 %d 人未完成本周工时填报：' % data['count']]
    for m in data['members'][:30]:
        state = '未填' if m['missing'] else ('已填 %d/%d' % (m['filled'], m['quota']))
        lines.append('· %s（%s）%s' % (m['name'], m['jobTitle'] or '—', state))
    if len(data['members']) > 30:
        lines.append('… 等共 %d 人' % len(data['members']))
    if app_url:
        lines.append('填报地址：%s' % app_url)
    return '\n'.join(lines)
