# -*- coding: utf-8 -*-
"""统一业务异常"""


class ApiError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details

    def to_dict(self):
        d = {'ok': False, 'code': self.code, 'message': self.message}
        if self.details is not None:
            d['details'] = self.details
        return d


def bad_request(msg, details=None):
    return ApiError('INVALID_INPUT', msg, 400, details)


def unauthorized(msg='请先登录'):
    return ApiError('UNAUTHORIZED', msg, 401)


def forbidden(msg='没有权限执行该操作'):
    return ApiError('FORBIDDEN', msg, 403)


def not_found(msg='数据不存在'):
    return ApiError('NOT_FOUND', msg, 404)


def validate_failed(errors, msg=None):
    return ApiError('VALIDATE_FAILED', msg or ('填报有 %d 处需要修改' % len(errors)),
                    422, {'errors': errors})
