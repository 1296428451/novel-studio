# -*- coding: utf-8 -*-
"""小说创作助手 - 纯 Python 版
主文件：python main.py  启动后访问 http://localhost:18000
功能：长篇小说审校 + AI 创作（分镜生成）

本文件只负责：应用创建、页面路由、API 配置路由与启动入口。
业务 API 拆分在 api_review.py / api_create.py / api_skills.py，
全局错误处理在 errors.py。
"""
import os

import requests
from flask import Flask, request, jsonify, send_from_directory

import utils
from errors import register_error_handlers
from api_review import bp as review_bp
from api_create import bp as create_bp
from api_skills import bp as skills_bp

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_ROOT, "public")
PORT = int(os.environ.get("PORT", 18000))

app = Flask(__name__, static_folder=None)
register_error_handlers(app)
app.register_blueprint(review_bp)
app.register_blueprint(create_bp)
app.register_blueprint(skills_bp)


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
    merged.update({k: v for k, v in cfg.items() if k in ("baseUrl", "apiKey", "model")})
    utils.save_config(merged)
    return jsonify({"ok": True, "config": merged})


@app.route("/api/models", methods=["GET"])
def api_models():
    config = utils.get_config()
    base_url = str(config.get("baseUrl") or "").strip()
    api_key = config.get("apiKey") or ""
    if not base_url or not api_key:
        return jsonify({"error": "需要先保存 Base URL 和 API Key"}), 400
    if not base_url.endswith("/"):
        base_url += "/"
    try:
        resp = requests.get(
            base_url + "models",
            headers={"Authorization": "Bearer " + api_key},
            timeout=15,
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


# ---------------- 启动 ----------------
if __name__ == "__main__":
    utils.ensure_data_layout()
    utils.migrate_legacy_review_data()
    print("小说创作助手 running: http://localhost:%d" % PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
