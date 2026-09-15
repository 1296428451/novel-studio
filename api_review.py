# -*- coding: utf-8 -*-
"""审校流程 API：创建会话、剧情总结、分块、逐块检测、历史与结果。"""
import os
import shutil

from flask import Blueprint, jsonify, request

import utils
from errors import upstream_error_response

bp = Blueprint("review", __name__)


# ---------------- 请求小助手 ----------------
def _body():
    return request.get_json(force=True, silent=True) or {}


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _parse_index(body, total):
    """解析并校验 index。非法时返回 (None, error_response)。"""
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return None, _err("index 非法")
    if index < 0 or index >= total:
        return None, _err("index 越界")
    return index, None


# ---------------- 创建会话 ----------------
@bp.route("/api/process/start", methods=["POST"])
def api_start():
    text = str(_body().get("text") or "").strip()
    if not text:
        return _err("文本为空")
    config = utils.get_config()
    if not config.get("baseUrl") or not config.get("apiKey") or not config.get("model"):
        return _err("未配置 API，请先到配置页填写 baseUrl / apiKey / model")

    time_id = utils.now_time()
    d = utils.ensure_time_dir(time_id)
    with open(os.path.join(d, "original.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    windows = utils.chunk_windows(text)
    utils.write_json(os.path.join(d, "chunks.json"), windows)
    utils.save_progress(d, {"summaryDone": [], "splitDone": [], "evaluateDone": []})
    utils.write_json(os.path.join(d, "meta.json"),
                     {"title": text[:60], "created": time_id})

    return jsonify({
        "ok": True,
        "time": time_id,
        "chunkTotal": len(windows),
        "chunkSize": utils.CHUNK_SIZE,
        "chunkOverlap": utils.CHUNK_OVERLAP,
    })


@bp.route("/api/process/status", methods=["GET"])
def api_status():
    time_id = request.args.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.run_dir(time_id)
    if not os.path.exists(d):
        return _err("结果不存在", 404)
    prog = utils.get_progress(d)
    windows = utils.read_json(os.path.join(d, "chunks.json"), [])
    return jsonify({
        "time": time_id,
        "chunkTotal": len(windows),
        "summaryDone": prog["summaryDone"],
        "splitDone": prog["splitDone"],
        "evaluateDone": prog["evaluateDone"],
        "splitBlockCount": len(utils.read_json(os.path.join(d, "split.json"), [])),
        "evaluateCount": len(utils.read_json(os.path.join(d, "suggestion.json"), [])),
        "summary": utils.read_text(os.path.join(d, "summary.md")),
    })


# ---- 步骤1：总结 ----
@bp.route("/api/process/summary", methods=["POST"])
def api_summary():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    config = utils.get_config()
    windows = utils.read_json(os.path.join(d, "chunks.json"), [])
    prog = utils.get_progress(d)
    summaries = utils.read_json(os.path.join(d, "summaries.json"), {})

    for i in range(len(windows)):
        if i in prog["summaryDone"]:
            continue
        content = utils._summary_window(d, windows, i, config)
        if content:
            summaries[str(i)] = content
            utils.write_json(os.path.join(d, "summaries.json"), summaries)
        prog = utils.mark_done(d, prog, "summaryDone", i)

    summary = utils._rebuild_summary_md(d, windows)
    return jsonify({"ok": True, "summary": summary, "chunkTotal": len(windows),
                    "processed": len(prog["summaryDone"])})


@bp.route("/api/process/summary/step", methods=["POST"])
def api_summary_step():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    windows = utils.read_json(os.path.join(d, "chunks.json"), [])
    index, err = _parse_index(body, len(windows))
    if err:
        return err

    prog = utils.get_progress(d)
    if index not in prog["summaryDone"]:
        try:
            content = utils._summary_window(d, windows, index, utils.get_config())
        except Exception as e:
            return upstream_error_response(e)
        if content:
            summaries = utils.read_json(os.path.join(d, "summaries.json"), {})
            summaries[str(index)] = content
            utils.write_json(os.path.join(d, "summaries.json"), summaries)
        utils._rebuild_summary_md(d, windows)
        prog = utils.mark_done(d, prog, "summaryDone", index)

    return jsonify({"ok": True, "processed": len(prog["summaryDone"]),
                    "total": len(windows), "summaryDone": prog["summaryDone"]})


# ---- 步骤2：分块 ----
@bp.route("/api/process/split", methods=["POST"])
def api_split():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    windows = utils.read_json(os.path.join(d, "chunks.json"), [])
    prog = utils.get_progress(d)
    for i in range(len(windows)):
        if i in prog["splitDone"]:
            continue
        utils._split_one(d, time_id, i)
        prog = utils.mark_done(d, prog, "splitDone", i)
    block_count = len(utils.read_json(os.path.join(d, "split.json"), []))
    return jsonify({"ok": True, "processed": len(prog["splitDone"]),
                    "total": len(windows), "blockCount": block_count})


@bp.route("/api/process/split/step", methods=["POST"])
def api_split_step():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    windows = utils.read_json(os.path.join(d, "chunks.json"), [])
    index, err = _parse_index(body, len(windows))
    if err:
        return err

    prog = utils.get_progress(d)
    if index not in prog["splitDone"]:
        try:
            utils._split_one(d, time_id, index)
        except Exception as e:
            return upstream_error_response(e)
        prog = utils.mark_done(d, prog, "splitDone", index)

    block_count = len(utils.read_json(os.path.join(d, "split.json"), []))
    return jsonify({"ok": True, "processed": len(prog["splitDone"]),
                    "total": len(windows), "blockCount": block_count,
                    "splitDone": prog["splitDone"]})


# ---- 步骤3：评估 ----
@bp.route("/api/process/evaluate", methods=["POST"])
def api_evaluate():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    blocks = utils.read_json(os.path.join(d, "split.json"), [])
    prog = utils.get_progress(d)
    for i in range(len(blocks)):
        if i in prog["evaluateDone"]:
            continue
        utils._evaluate_one(d, time_id, i)
        prog = utils.mark_done(d, prog, "evaluateDone", i)
    count = len(utils.read_json(os.path.join(d, "suggestion.json"), []))
    return jsonify({"ok": True, "processed": len(prog["evaluateDone"]),
                    "total": len(blocks), "count": count})


@bp.route("/api/process/evaluate/step", methods=["POST"])
def api_evaluate_step():
    body = _body()
    time_id = body.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.ensure_time_dir(time_id)
    blocks = utils.read_json(os.path.join(d, "split.json"), [])
    index, err = _parse_index(body, len(blocks))
    if err:
        return err

    prog = utils.get_progress(d)
    changed = 0
    if index not in prog["evaluateDone"]:
        try:
            changed = utils._evaluate_one(d, time_id, index)
        except Exception as e:
            return upstream_error_response(e)
        prog = utils.mark_done(d, prog, "evaluateDone", index)

    count = len(utils.read_json(os.path.join(d, "suggestion.json"), []))
    return jsonify({"ok": True, "processed": len(prog["evaluateDone"]),
                    "total": len(blocks), "count": count,
                    "newItems": changed, "evaluateDone": prog["evaluateDone"]})


# ---------------- 审核历史与结果 ----------------
@bp.route("/api/history", methods=["GET"])
def api_history():
    entries = []
    if os.path.isdir(utils.REVIEW_DATA_DIR):
        for name in sorted(os.listdir(utils.REVIEW_DATA_DIR), reverse=True):
            dd = os.path.join(utils.REVIEW_DATA_DIR, name)
            if not os.path.isdir(dd):
                continue
            if not os.path.exists(os.path.join(dd, "original.txt")):
                continue
            meta = utils.read_json(os.path.join(dd, "meta.json"), {})
            prog = utils.get_progress(dd)
            chunk_total = len(utils.read_json(os.path.join(dd, "chunks.json"), []))
            split_block = len(utils.read_json(os.path.join(dd, "split.json"), []))
            evaluate_count = len(utils.read_json(os.path.join(dd, "suggestion.json"), []))
            completed = (
                chunk_total > 0 and
                len(prog["summaryDone"]) == chunk_total and
                len(prog["splitDone"]) == chunk_total and
                len(prog["evaluateDone"]) == split_block
            )
            entries.append({
                "time": name,
                "title": meta.get("title", "") or name,
                "created": meta.get("created", name),
                "chunkTotal": chunk_total,
                "summaryDoneCount": len(prog["summaryDone"]),
                "splitDoneCount": len(prog["splitDone"]),
                "splitBlockCount": split_block,
                "evaluateDoneCount": len(prog["evaluateDone"]),
                "evaluateCount": evaluate_count,
                "completed": completed,
            })
    return jsonify(entries)


@bp.route("/api/history", methods=["DELETE"])
def api_history_delete():
    time_id = request.args.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.run_dir(time_id)
    if not os.path.exists(d):
        return _err("记录不存在", 404)
    shutil.rmtree(d)
    return jsonify({"ok": True})


@bp.route("/api/result", methods=["GET"])
def api_result():
    time_id = request.args.get("time")
    if not time_id:
        return _err("缺少 time")
    d = utils.run_dir(time_id)
    if not os.path.exists(d):
        return _err("结果不存在", 404)
    original = utils.read_text(os.path.join(d, "original.txt"))
    summary = utils.read_text(os.path.join(d, "summary.md"))
    split = utils.read_json(os.path.join(d, "split.json"), [])
    suggestions = utils.read_json(os.path.join(d, "suggestion.json"), [])
    return jsonify({"time": time_id, "original": original, "summary": summary,
                    "split": split, "suggestions": suggestions})


@bp.route("/api/affirm", methods=["POST"])
def api_affirm():
    body = _body()
    time_id = body.get("time")
    item_id = body.get("id")
    if not time_id or not item_id:
        return _err("缺少 time/id")
    d = utils.run_dir(time_id)
    file_path = os.path.join(d, "suggestion.json")
    items = utils.read_json(file_path, [])
    idx = next((i for i, s in enumerate(items) if s.get("id") == item_id), -1)
    if idx == -1:
        return _err("未找到该项", 404)
    items[idx]["userAffirm"] = str(body.get("userAffirm") or "")
    utils.write_json(file_path, items)
    return jsonify({"ok": True, "item": items[idx]})
