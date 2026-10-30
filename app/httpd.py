# -*- coding: utf-8 -*-
"""HTTP 服务：静态页面 + JSON 接口"""
import http.server
import json
import os
import socketserver
import sys
import urllib.parse
from datetime import datetime

from . import api, auth, config, db

COOKIE_NAME = 'ts_token'
MAX_BODY = 20 * 1024 * 1024   # 20MB，够传 Excel


def _log(msg):
    sys.stdout.write('[%s] %s\n' % (datetime.now().strftime('%H:%M:%S'), msg))
    sys.stdout.flush()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'WorkHoursServer/1.0'
    protocol_version = 'HTTP/1.1'

    # -------------------------------------------------- 日志
    def log_message(self, fmt, *args):
        if '/api/' in (args[0] if args else ''):
            return                      # 接口日志由 api 层按需输出，避免刷屏
        _log('%s %s' % (self.address_string(), fmt % args))

    # -------------------------------------------------- 入口
    def do_GET(self):
        self._handle('GET')

    def do_POST(self):
        self._handle('POST')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Allow', 'GET, POST, OPTIONS')
        self.send_header('Content-Length', '0')
        self.end_headers()

    # -------------------------------------------------- 核心
    def _handle(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path or '/')
        query = urllib.parse.parse_qs(parsed.query)

        if not api.is_api(path):
            return self._serve_static(path)

        # 读请求体
        raw = b''
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self._send_json(413, {'ok': False, 'code': 'TOO_LARGE',
                                         'message': '上传内容超过 20MB'})
        if length > 0:
            raw = self.rfile.read(length)

        ctype = (self.headers.get('Content-Type') or '').lower()
        body = {}
        if raw and 'json' in ctype:
            try:
                body = json.loads(raw.decode('utf-8')) or {}
            except Exception:
                body = {}
        elif raw and 'x-www-form-urlencoded' in ctype:
            body = {k: v[0] for k, v in urllib.parse.parse_qs(
                raw.decode('utf-8', 'replace')).items()}

        token = (self.headers.get('X-Token') or '').strip() or self._cookie(COOKIE_NAME)
        user = auth.get_session_user(token)

        ctx = {
            'user': user,
            'token': token,
            'ip': self.client_address[0] if self.client_address else '',
            'rawBody': raw,
            'userAgent': self.headers.get('User-Agent') or '',
        }

        try:
            status, payload = api.dispatch(method, path, query, body, ctx)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._send_json(500, {'ok': False, 'code': 'INTERNAL_ERROR',
                                         'message': '服务内部错误：%s' % e})

        if isinstance(payload, api.FileResponse):
            return self._send_file(payload)
        return self._send_json(status, payload)

    # -------------------------------------------------- 静态
    def _serve_static(self, path):
        if path == '/favicon.ico':
            return self._send_bytes(204, b'', 'text/plain')
        full = api.resolve_static(path)
        if not full:
            return self._send_bytes(
                404,
                ('<meta charset="utf-8"><h3>404 找不到页面</h3>'
                 '<p><a href="/">回到首页</a></p>').encode('utf-8'),
                'text/html; charset=utf-8')
        try:
            with open(full, 'rb') as f:
                data = f.read()
        except OSError:
            return self._send_bytes(500, b'read error', 'text/plain')
        return self._send_bytes(200, data, api.content_type_of(full), no_store=True)

    # -------------------------------------------------- 响应
    def _send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self._extra_headers(payload)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _extra_headers(self, payload):
        # 登录成功时下发 Cookie
        if isinstance(payload, dict) and payload.get('token'):
            tok = payload['token']
            max_age = config.SESSION_TTL_DAYS * 86400
            self.send_header('Set-Cookie',
                             '%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax'
                             % (COOKIE_NAME, tok, max_age))
        if isinstance(payload, dict) and payload.get('ok') is False and \
                payload.get('code') == 'UNAUTHORIZED':
            self.send_header('Set-Cookie', '%s=; Path=/; Max-Age=0' % COOKIE_NAME)

    def _send_file(self, fr):
        try:
            if fr.path:
                size = os.path.getsize(fr.path)
                f = open(fr.path, 'rb')
            else:
                data = fr.data.read() if hasattr(fr.data, 'read') else fr.data
                size = len(data)
                f = None
        except OSError:
            return self._send_json(500, {'ok': False, 'code': 'FILE_ERROR',
                                         'message': '文件读取失败'})

        fname = fr.filename or 'download'
        quoted = urllib.parse.quote(fname)
        self.send_response(200)
        self.send_header('Content-Type', fr.content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Content-Disposition',
                         "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (quoted, quoted))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            if f is not None:
                with f:
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            else:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_bytes(self, status, data, ctype, no_store=False):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        if no_store:
            self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if data:
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _cookie(self, name):
        raw = self.headers.get('Cookie') or ''
        for part in raw.split(';'):
            if '=' in part:
                k, v = part.split('=', 1)
                if k.strip() == name:
                    return v.strip()
        return ''


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # Windows 上 SO_REUSEADDR 允许两个进程绑同一端口（第二个静默"成功"），
    # 会导致"看起来启动了但访问到的是旧服务"。这里关掉，让端口冲突直接报错，
    # 由 server.py 的端口避让逻辑接管。
    allow_reuse_address = (os.name != 'nt')


def serve():
    db.init_db()
    auth.cleanup_sessions()
    httpd = ThreadingServer((config.HOST, config.PORT), Handler)
    return httpd
