# -*- coding: utf-8 -*-
"""AI 创作 API：分镜生成（SSE 流式透传）、创作历史与结果。"""
import json
import os
import shutil

from flask import Blueprint, Response, jsonify, request

import prompts
import utils

bp = Blueprint("create", __name__)

RETRYABLE_CODES = (429, 500, 502, 503, 504)


def _body():
    return request.get_json(force=True, silent=True) or {}


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _sse(obj):
    """把一个事件对象编码为 SSE 帧（单行 data + 空行分隔）。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@bp.route("/api/create/history", methods=["GET"])
def api_create_history():
    entries = []
    if os.path.isdir(utils.CREATE_DATA_DIR):
        for name in sorted(os.listdir(utils.CREATE_DATA_DIR), reverse=True):
            dd = os.path.join(utils.CREATE_DATA_DIR, name)
            if not os.path.isdir(dd):
                continue
            if not os.path.exists(os.path.join(dd, "input.json")):
                continue
            meta = utils.read_json(os.path.join(dd, "input.json"), {})
            err = utils.read_json(os.path.join(dd, "error.json"), {})
            entries.append({
                "time": name,
                "prompt": str(meta.get("prompt", "") or ""),
                "skills": meta.get("skills", []),
                "hasOutput": os.path.exists(os.path.join(dd, "output.txt")),
                "error": str(err.get("error", "")) if isinstance(err, dict) else "",
            })
    return jsonify(entries)


@bp.route("/api/create/result", methods=["GET"])
def api_create_result():
    time_id = request.args.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.create_run_dir(time_id)
    if not os.path.exists(d):
        return _err("结果不存在", 404)
    inp = utils.read_json(os.path.join(d, "input.json"), {})
    output = utils.recover_mojibake(utils.read_text(os.path.join(d, "output.txt")))
    resp = {
        "time": time_id,
        "prompt": inp.get("prompt", ""),
        "skills": inp.get("skills", []),
        "output": output,
    }
    # 无产出但有错误记录（生成失败）：把失败原因带给前端
    if not output:
        err = utils.read_json(os.path.join(d, "error.json"), {})
        if isinstance(err, dict) and err.get("error"):
            resp["error"] = str(err["error"])
    return jsonify(resp)


@bp.route("/api/create/history", methods=["DELETE"])
def api_create_history_delete():
    time_id = request.args.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.create_run_dir(time_id)
    if not os.path.exists(d):
        return _err("记录不存在", 404)
    shutil.rmtree(d)
    return jsonify({"ok": True})


@bp.route("/api/create/generate", methods=["POST"])
def api_create_generate():
    body = _body()
    user_prompt = str(body.get("prompt") or "").strip()
    skill_names = body.get("skills", [])
    if not user_prompt:
        return _err("请输入创作需求")
    if not isinstance(skill_names, list):
        return _err("skills 必须是数组")

    config = utils.get_config()
    if not config.get("baseUrl") or not config.get("apiKey") or not config.get("model"):
        return _err("未配置 API，请先到配置页填写 baseUrl / apiKey / model")

    skills = []
    for name in skill_names:
        safe_name = os.path.basename(str(name))
        fpath = os.path.join(utils.SKILL_DIR, safe_name)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                skills.append((os.path.splitext(safe_name)[0], f.read()))

    p = prompts.create_prompt(user_prompt, skills)

    # 先落盘本次会话参数：即使中途失败/断开，历史里也有记录可查
    time_id = utils.now_time()
    d = utils.ensure_create_time_dir(time_id)
    utils.write_json(os.path.join(d, "input.json"), {
        "prompt": user_prompt,
        "skills": skill_names,
        "system_prompt": p["system"],
    })

    def _record_error(err_msg, code):
        utils.write_json(os.path.join(d, "error.json"), {
            "error": err_msg,
            "httpStatus": code,
            "retryable": code in RETRYABLE_CODES,
        })

    def gen():
        accumulated = []
        try:
            yield _sse({"type": "meta", "time": time_id})
            for delta in utils.chat_stream(config, p["system"], p["user"]):
                accumulated.append(delta)
                yield _sse({"type": "delta", "text": delta})
            output = utils.strip_reasoning("".join(accumulated))
            if not output:
                raise utils.UpstreamError("API 响应未包含任何文本内容", 502)
            with open(os.path.join(d, "output.txt"), "w", encoding="utf-8") as f:
                f.write(output)
            yield _sse({"type": "done", "time": time_id, "output": output})
        except utils.UpstreamError as e:
            _record_error(str(e), e.http_status)
            yield _sse({"type": "error", "error": str(e), "time": time_id,
                        "retryable": e.http_status in RETRYABLE_CODES})
        except Exception as e:
            _record_error(str(e), 500)
            yield _sse({"type": "error", "error": str(e), "time": time_id,
                        "retryable": True})

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
