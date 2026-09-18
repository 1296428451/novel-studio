# -*- coding: utf-8 -*-
"""AI 会话历史 API：保存 / 列表 / 加载 / 删除。

保存格式参考 data/create/{time}/：每个会话一个以时间命名的文件夹，
内含 chat.json，记录 system_prompt、provider 与完整 messages 列表。
"""
import os
import re
import shutil

from flask import Blueprint, jsonify, request

import utils

bp = Blueprint("chat", __name__)

_SANE = re.compile(r"[^0-9A-Za-z_\-]")


def _sane_id(s):
    """过滤 time id，避免路径穿越。"""
    return _SANE.sub("", str(s or ""))


def _err(msg, code=400):
    return jsonify({"error": msg}), code


@bp.route("/api/chat/save", methods=["POST"])
def api_chat_save():
    body = request.get_json(force=True, silent=True) or {}
    messages = body.get("messages")
    if not isinstance(messages, list):
        return _err("messages 必须是数组")

    time_id = _sane_id(body.get("time")) or utils.now_time()
    d = utils.ensure_chat_time_dir(time_id)

    previous = utils.read_json(os.path.join(d, "chat.json"), {})
    created_at = previous.get("created_at") or utils.now_time()

    # 自动标题：优先用传入 title，否则取首条用户消息
    title = str(body.get("title") or "").strip()
    if not title:
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    title = c.strip()[:40]
                    break
        if not title:
            title = "会话 " + time_id

    data = {
        "time": time_id,
        "title": title,
        "system_prompt": str(body.get("system_prompt") or ""),
        "provider": str(body.get("provider") or ""),
        "messages": messages,
        "created_at": created_at,
        "updated_at": utils.now_time(),
    }
    utils.write_json(os.path.join(d, "chat.json"), data)
    return jsonify({"ok": True, "time": time_id})


@bp.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    entries = []
    if os.path.isdir(utils.CHAT_DATA_DIR):
        for name in sorted(os.listdir(utils.CHAT_DATA_DIR), reverse=True):
            dd = os.path.join(utils.CHAT_DATA_DIR, name)
            if not os.path.isdir(dd):
                continue
            data = utils.read_json(os.path.join(dd, "chat.json"), {})
            if not isinstance(data, dict):
                continue
            msgs = data.get("messages", []) if isinstance(data.get("messages"), list) else []
            preview = ""
            for m in msgs:
                if isinstance(m, dict) and m.get("role") == "user":
                    c = m.get("content")
                    if isinstance(c, str) and c.strip():
                        preview = c.strip()[:80]
                        break
            entries.append({
                "time": name,
                "title": str(data.get("title") or "") or preview[:40],
                "provider": str(data.get("provider") or ""),
                "system_prompt": str(data.get("system_prompt") or ""),
                "message_count": len(msgs),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "preview": preview,
            })
    return jsonify(entries)


@bp.route("/api/chat/session", methods=["GET"])
def api_chat_session():
    time_id = _sane_id(request.args.get("time"))
    if not time_id:
        return _err("缺少 time")
    d = utils.chat_run_dir(time_id)
    if not os.path.exists(d):
        return _err("会话不存在", 404)
    data = utils.read_json(os.path.join(d, "chat.json"), None)
    if not isinstance(data, dict):
        return _err("会话数据损坏", 404)
    return jsonify(data)


@bp.route("/api/chat/history", methods=["DELETE"])
def api_chat_history_delete():
    time_id = _sane_id(request.args.get("time"))
    if not time_id:
        return _err("缺少 time")
    d = utils.chat_run_dir(time_id)
    if not os.path.exists(d):
        return _err("记录不存在", 404)
    shutil.rmtree(d)
    return jsonify({"ok": True})
