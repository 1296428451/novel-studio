# -*- coding: utf-8 -*-
"""小说创作助手 - 纯 Python 版
主文件：python main.py  启动后访问 http://localhost:18000
功能：长篇小说审校 + AI 创作（分镜生成）

本文件只负责：应用创建、页面路由、API 配置路由与启动入口。
业务 API 拆分在 api_review.py / api_create.py / api_skills.py，
全局错误处理在 errors.py。
"""
import os

import json
import requests
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

import utils
from errors import register_error_handlers
from api_review import bp as review_bp
from api_create import bp as create_bp
from api_skills import bp as skills_bp
from api_chat import bp as chat_bp

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_ROOT, "public")
PORT = int(os.environ.get("PORT", 18007))

app = Flask(__name__, static_folder=None)
register_error_handlers(app)
app.register_blueprint(review_bp)
app.register_blueprint(create_bp)
app.register_blueprint(skills_bp)
app.register_blueprint(chat_bp)


# ---------------- 页面 ----------------
@app.route("/")
def index_page():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:name>")
def static_files(name):
    return send_from_directory(PUBLIC_DIR, name)


# ---------------- 配置 ----------------
@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(utils.get_config())
    cfg = request.get_json(force=True, silent=True) or {}
    merged = dict(utils.get_config())
    allowed_keys = ("baseUrl", "apiKey", "model", "proxy_mode", "proxy_url",
                    "providers", "defaultProvider")
    merged.update({k: v for k, v in cfg.items() if k in allowed_keys})
    utils.save_config(merged)
    return jsonify({"ok": True, "config": merged})


@app.route("/api/models", methods=["GET", "POST"])
def api_models():
    # POST：直接用请求体里的 baseUrl / apiKey 获取（新增/编辑提供商时尚未保存也可测试）
    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        base_url = str(body.get("baseUrl") or "").strip()
        api_key = body.get("apiKey") or ""
    else:
        provider_id = request.args.get("provider")
        config = utils.get_config()
        if provider_id:
            prov = next((p for p in config.get("providers", []) if p.get("id") == provider_id), None)
            if not prov:
                return jsonify({"error": "未找到指定的 API 提供商"}), 400
        else:
            prov = {"baseUrl": config.get("baseUrl", ""), "apiKey": config.get("apiKey", "")}
        base_url = str(prov.get("baseUrl") or "").strip()
        api_key = prov.get("apiKey") or ""

    if not base_url or not api_key:
        return jsonify({"error": "需要先填写 Base URL 和 API Key"}), 400
    if not base_url.endswith("/"):
        base_url += "/"
    proxies = utils.get_proxies(utils.get_config())
    try:
        resp = requests.get(
            base_url + "models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=15,
            proxies=proxies,
        )
    except Exception as e:
        return jsonify({"error": "请求模型列表失败：" + str(e)}), 502
    try:
        data = resp.json()
    except ValueError:
        return jsonify({"error": "模型列表接口返回非 JSON（HTTP %s）" % resp.status_code}), 502
    if resp.status_code != 200:
        err = data.get("error", {}).get("message", "") or str(data)[:200]
        return jsonify({"error": "获取模型列表失败（HTTP %s）：%s" % (resp.status_code, err)}), 502
    models = sorted(m.get("id") or "" for m in data.get("data", []) if m.get("id"))
    return jsonify({"models": models})


# ---------------- AI 会话（流式） ----------------
@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    provider_id = body.get("provider")
    messages = body.get("messages") or []
    try:
        temperature = float(body.get("temperature", 0.7))
    except (TypeError, ValueError):
        temperature = 0.7

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "messages 不能为空"}), 400

    config = utils.get_config()
    prov_cfg = utils.get_provider_config(config, provider_id)
    if prov_cfg is None:
        return jsonify({"error": "没有可用的 API 提供商，请先到「API 配置」页添加"}), 400
    if not prov_cfg.get("baseUrl") or not prov_cfg.get("apiKey"):
        return jsonify({"error": "所选提供商缺少 Base URL 或 API Key"}), 400
    if not prov_cfg.get("model"):
        return jsonify({"error": "所选提供商未设置模型名（model）"}), 400

    def gen():
        try:
            for piece in utils.chat_stream(prov_cfg, messages=messages, temperature=temperature):
                payload = json.dumps({"content": piece}, ensure_ascii=False)
                yield ("data: " + payload + "\n\n").encode("utf-8")
            yield b"data: [DONE]\n\n"
        except utils.UpstreamError as e:
            err = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield ("data: " + err + "\n\n").encode("utf-8")
            yield b"data: [DONE]\n\n"
        except Exception as e:
            err = json.dumps({"error": "对话出错：" + str(e)}, ensure_ascii=False)
            yield ("data: " + err + "\n\n").encode("utf-8")
            yield b"data: [DONE]\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------- 启动 ----------------
if __name__ == "__main__":
    utils.ensure_data_layout()
    utils.migrate_legacy_review_data()
    print("小说创作助手 running: http://localhost:%d" % PORT)
    # threaded=True：AI 会话的 /api/chat 是 SSE 流式响应。
    # 单线程（默认）下 Werkzeug 会把流式响应缓冲到生成器结束才一次性下发，
    # 导致浏览器点「发送」后长时间无响应（实测首字延迟约 57s）。
    # 开启多线程后，SSE 可逐段实时下发，且能并行处理历史保存/加载等并发请求。
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)