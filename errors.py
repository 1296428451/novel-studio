# -*- coding: utf-8 -*-
"""全局错误处理：所有异常统一返回 JSON，而非 Flask 默认的 HTML 错误页。"""
from flask import jsonify
from werkzeug.exceptions import HTTPException

import utils


def json_error(e, status=500):
    msg = str(getattr(e, "description", "") or getattr(e, "message", "") or "")
    if not msg:
        msg = e.__class__.__name__
    return jsonify({"ok": False, "error": msg, "code": getattr(e, "code", status)}), status


def upstream_error_response(e):
    """把上游调用异常统一转成带明确状态码的 JSON 错误响应（供审校各步骤使用）。"""
    code = e.http_status if isinstance(e, utils.UpstreamError) else 500
    return jsonify({"ok": False, "error": "AI 调用失败：" + str(e),
                    "retryable": code in (429, 500, 502, 503, 504)}), code


def register_error_handlers(app):
    """把统一的 JSON 错误处理挂到 app 上。"""

    @app.errorhandler(404)
    def _404(e):
        return json_error(e, 404)

    @app.errorhandler(405)
    def _405(e):
        return json_error(e, 405)

    @app.errorhandler(HTTPException)
    def _http_exception(e):
        return json_error(e, e.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(e):
        return json_error(e, 500)
