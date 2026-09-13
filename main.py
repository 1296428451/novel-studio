# -*- coding: utf-8 -*-
"""长篇小说审校系统 - 纯 Python 版
主文件：python main.py  启动后访问 http://localhost:18000
"""
import os
import re
import json
import time

import requests
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException

import prompts

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_ROOT, "public")
DATA_DIR = os.path.join(APP_ROOT, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
PORT = int(os.environ.get("PORT", 18000))

# 长文本窗口参数
CHUNK_LIMIT = 5000      # 超过该字数必须拆分
CHUNK_SIZE = 3000       # 每组字数
CHUNK_OVERLAP = 500     # 交叉重叠字数

app = Flask(__name__, static_folder=None)


# ---------------- 基础工具 ----------------
def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"baseUrl": "", "apiKey": "", "model": ""}


def save_config(cfg):
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def now_time():
    return time.strftime("%Y%m%d_%H%M%S")


def run_dir(time_id):
    return os.path.join(DATA_DIR, time_id)


def ensure_time_dir(time_id):
    d = run_dir(time_id)
    os.makedirs(d, exist_ok=True)
    return d


def read_json(file_path, fallback):
    if not os.path.exists(file_path):
        return fallback
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def write_json(file_path, obj):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------------- 处理进度持久化 ----------------
def get_progress(d):
    """读取某次运行的进度，字段分别为已完成的：总结窗口、分块窗口、评估块 的索引列表。"""
    p = read_json(os.path.join(d, "progress.json"), {})
    return {
        "summaryDone": sorted(set(p.get("summaryDone", []))),
        "splitDone": sorted(set(p.get("splitDone", []))),
        "evaluateDone": sorted(set(p.get("evaluateDone", []))),
    }


def save_progress(d, prog):
    write_json(os.path.join(d, "progress.json"), {
        "summaryDone": sorted(set(prog.get("summaryDone", []))),
        "splitDone": sorted(set(prog.get("splitDone", []))),
        "evaluateDone": sorted(set(prog.get("evaluateDone", []))),
    })


def mark_done(d, prog, key, index):
    """把 index 标记为已完成并保存（幂等）。"""
    done = set(prog.get(key, []))
    done.add(int(index))
    prog[key] = sorted(done)
    save_progress(d, prog)
    return prog


def read_text(file_path, fallback=""):
    if not os.path.exists(file_path):
        return fallback
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------- 长文本窗口拆分 ----------------
def chunk_windows(text, limit=CHUNK_LIMIT, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """若文本超过 limit 字，则按 size 一组（相邻窗口交叉 overlap 字）拆分，否则为单个窗口。"""
    if len(text) <= limit:
        return [text]
    windows = []
    start = 0
    n = len(text)
    while start < n:
        windows.append(text[start:start + size])
        if start + size >= n:
            break
        start += size - overlap
    return windows


# ---------------- 行号处理 ----------------
def original_lines(text):
    return text.split("\n")


def find_line(lines, target, from_idx):
    """在 lines 中从 from_idx 起查找与 target 相同的行，返回下标或 -1。"""
    for i in range(from_idx, len(lines)):
        if lines[i] == target:
            return i
    return -1


def number_blocks(blocks, lines):
    """给每个块内的每一行分配其在原文中的全局行号（按出现顺序贪心匹配），返回与 blocks 同构的行号列表。"""
    out = []
    ptr = 0
    for block in blocks:
        nums = []
        for ln in block:
            idx = find_line(lines, ln, ptr)
            if idx != -1:
                nums.append(idx + 1)
                ptr = idx + 1
            else:
                nums.append(ptr)  # 兜底，保持单调不越界
        out.append(nums)
    return out


# ---------------- OpenAI 兼容接口调用 ----------------
def _extract_text_from_content(content):
    """OpenAI 兼容接口 content 可能是字符串、列表(多段)或缺失，统一提取为纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for it in content:
            if isinstance(it, dict):
                t = it.get("text") or it.get("output_text") or it.get("content")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(it, str):
                parts.append(it)
        return "\n".join(parts)
    return str(content)


def _extract_message_text(message):
    """从 message 中取最终回答文本。
    思考模型把推理过程放在 reasoning_content/thinking，最终答案在 content。
    若 content 为空而 reasoning 有内容，则回退抓取 reasoning 中最像答案的部分。"""
    content = _extract_text_from_content(message.get("content"))
    if content and "<!doctype" not in content.lower() and content.strip():
        return content

    # content 缺失/为空 -> 回退 reasoning
    reasoning = ""
    for key in ("reasoning_content", "thinking", "reasoning", "thought"):
        v = message.get(key)
        if isinstance(v, str):
            reasoning += v
        elif isinstance(v, (list, tuple)):
            reasoning += _extract_text_from_content(v)
    if reasoning and "<!doctype" not in reasoning.lower() and reasoning.strip():
        return reasoning
    return content


def strip_reasoning(text):
    """去掉思考模型混入的 think/reasoning 标志（连同内部内容），并剔除 HTML 残留。"""
    body = str(text or "")
    import re as _re
    # 去掉整段 think/reasoning 块（含内部内容），避免其内部的 [...] 干扰
    body = _re.sub(r"<\s*thinking[^>]*>[\s\S]{0,20000}?</\s*thinking\s*>", "", body, flags=_re.I)
    body = _re.sub(r"<\s*reasoning[^>]*>[\s\S]{0,20000}?</\s*reasoning\s*>", "", body, flags=_re.I)
    # 去掉独立的 think/reasoning 标签对
    body = _re.sub(r"<\s*/\s*?thinking>", "", body, flags=_re.I)
    body = _re.sub(r"<\s*thinking[^>]*>", "", body, flags=_re.I)
    body = _re.sub(r"<\s*/\s*?reasoning>", "", body, flags=_re.I)
    body = _re.sub(r"<\s*reasoning[^>]*>", "", body, flags=_re.I)
    # 去掉其它成对/自成闭合的 html 标签，避免 '<' 干扰 JSON
    body = _re.sub(r"<[^>]{1,200}>", "", body)
    # 去掉代码块围栏
    body = _re.sub(r"```(?:json)?\s*", "", body, flags=_re.I)
    body = body.replace("```", "")
    return body


def chat(config, system_prompt, user_content):
    base_url = str(config.get("baseUrl") or "").strip()
    api_key = config.get("apiKey") or ""
    model = config.get("model") or ""
    if not base_url.endswith("/"):
        base_url += "/"
    endpoint = base_url + "chat/completions"

    payload = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    resp = requests.post(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        json=payload,
        timeout=300,
    )

    # 非 JSON 响应（尤其上游返回 HTML 页面时）会被前端的 .json() 解析报 '<!doctype ...'
    ctype = (resp.headers.get("Content-Type") or "")
    if resp.status_code != 200:
        snippet = resp.text[:300] if resp.text else ""
        raise RuntimeError("上游 API 返回 %s（%s）：%s" % (resp.status_code, ctype, snippet))

    try:
        data = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise RuntimeError("上游 API 返回的不是 JSON（Content-Type=%s）：%s" % (ctype, snippet))

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("API 响应缺少 choices/message 字段：%s" % str(data)[:300])

    text = _extract_message_text(message)
    return strip_reasoning(text)


def extract_json_list(content):
    """从模型输出中鲁棒地提取 JSON 数组（兼容思考模型混入的推理文字）。"""
    text = str(content or "").strip()
    # 前面已剔除 html/think；此处再兜底
    text = strip_reasoning(text)
    if not text or text.lower().startswith("<!doctype") or not text.__contains__("["):
        return []

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fenced.group(1) if fenced else text

    start = -1
    end = -1
    brace_start = candidate.find("[")
    brace_end = candidate.rfind("]")
    # 若数组嵌在对象里，优先取最后一个成对数组
    if brace_start != -1 and brace_end > brace_start:
        start, end = brace_start, brace_end
    else:
        return []

    try:
        arr = json.loads(candidate[start:end + 1])
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


# ---------------- 页面 ----------------
@app.route("/")
def index_page():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/<path:name>")
def static_files(name):
    return send_from_directory(PUBLIC_DIR, name)


def _json_error(e, status=500):
    """把所有 /api 错误都转成 JSON，避免前端 .json() 收到 Flask 默认 HTML 页面报 '<!doctype ...'。"""
    msg = str(getattr(e, "description", "") or getattr(e, "message", "") or "")
    if not msg:
        msg = e.__class__.__name__
    return jsonify({"ok": False, "error": msg, "code": getattr(e, "code", status)}), status


@app.errorhandler(404)
def handle_404(e):
    return _json_error(e, 404)


@app.errorhandler(405)
def handle_405(e):
    return _json_error(e, 405)


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return _json_error(e, e.code or 500)


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """兜底：任何未捕获异常都以 JSON 形式返回，绝不返回 HTML。"""
    return _json_error(e, 500)


# ---------------- API ----------------
@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(get_config())
    cfg = request.get_json(force=True, silent=True) or {}
    merged = dict(get_config())
    merged.update({k: v for k, v in cfg.items() if k in ("baseUrl", "apiKey", "model")})
    save_config(merged)
    return jsonify({"ok": True, "config": merged})


@app.route("/api/process/start", methods=["POST"])
def api_start():
    body = request.get_json(force=True, silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "文本为空"}), 400
    config = get_config()
    if not config.get("baseUrl") or not config.get("apiKey") or not config.get("model"):
        return jsonify({"error": "未配置 API，请先到配置页填写 baseUrl / apiKey / model"}), 400

    time_id = now_time()
    d = ensure_time_dir(time_id)
    with open(os.path.join(d, "original.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    # 长文本拆分窗口
    windows = chunk_windows(text)
    write_json(os.path.join(d, "chunks.json"), windows)
    # 初始化处理进度与该次运行的元信息（供续接与历史记录使用）
    save_progress(d, {"summaryDone": [], "splitDone": [], "evaluateDone": []})
    write_json(os.path.join(d, "meta.json"),
               {"title": text[:60], "created": time_id})

    return jsonify({
        "ok": True,
        "time": time_id,
        "chunkTotal": len(windows),
        "chunkSize": CHUNK_SIZE,
        "chunkOverlap": CHUNK_OVERLAP,
    })


def _summary_window(d, windows, index, config):
    p = prompts.summary_prompt(windows[index])
    return chat(config, p["system"], p["user"])


def _rebuild_summary_md(d, windows):
    """从 summaries.json（index->文本）按窗口顺序合并出 summary.md，返回合并文本。"""
    summaries = read_json(os.path.join(d, "summaries.json"), {})
    ordered = [summaries.get(str(i), "").strip() for i in range(len(windows))]
    ordered = [s for s in ordered if s]
    summary = "\n\n---\n\n".join(ordered)
    with open(os.path.join(d, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    return summary


@app.route("/api/process/summary", methods=["POST"])
def api_summary():
    """第一次 API：对每个尚未总结的窗口分别总结，再合并为 summary.md（幂等可续接）。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    config = get_config()
    windows = read_json(os.path.join(d, "chunks.json"), [])
    prog = get_progress(d)
    summaries = read_json(os.path.join(d, "summaries.json"), {})

    for i in range(len(windows)):
        if i in prog["summaryDone"]:
            continue
        content = _summary_window(d, windows, i, config)
        if content:
            summaries[str(i)] = content
            write_json(os.path.join(d, "summaries.json"), summaries)
        prog = mark_done(d, prog, "summaryDone", i)

    summary = _rebuild_summary_md(d, windows)
    return jsonify({"ok": True, "summary": summary, "chunkTotal": len(windows),
                    "processed": len(prog["summaryDone"])})


@app.route("/api/process/summary/step", methods=["POST"])
def api_summary_step():
    """对第 index 个窗口做总结（若已完成则跳过），返回当前进度。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    windows = read_json(os.path.join(d, "chunks.json"), [])
    total = len(windows)
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return jsonify({"error": "index 非法"}), 400
    if index < 0 or index >= total:
        return jsonify({"error": "index 越界"}), 400

    prog = get_progress(d)
    if index not in prog["summaryDone"]:
        content = _summary_window(d, windows, index, get_config())
        if content:
            summaries = read_json(os.path.join(d, "summaries.json"), {})
            summaries[str(index)] = content
            write_json(os.path.join(d, "summaries.json"), summaries)
        _rebuild_summary_md(d, windows)
        prog = mark_done(d, prog, "summaryDone", index)

    return jsonify({"ok": True, "processed": len(prog["summaryDone"]),
                    "total": total, "summaryDone": prog["summaryDone"]})


@app.route("/api/process/split", methods=["POST"])
def api_split():
    """第二次 API：对每个尚未分块的窗口做分块（幂等可续接），返回总进度。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    windows = read_json(os.path.join(d, "chunks.json"), [])
    prog = get_progress(d)
    for i in range(len(windows)):
        if i in prog["splitDone"]:
            continue
        _split_one(d, time_id, i)
        prog = mark_done(d, prog, "splitDone", i)
    block_count = len(read_json(os.path.join(d, "split.json"), []))
    return jsonify({"ok": True, "processed": len(prog["splitDone"]),
                    "total": len(windows), "blockCount": block_count})


@app.route("/api/process/split/step", methods=["POST"])
def api_split_step():
    """第二次 API（循环，幂等）：对第 index 个窗口分块，返回当前进度 {已处理}/{总数}。
    若该窗口已分块完成则直接跳过，供出错后【重试】续接进度。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    windows = read_json(os.path.join(d, "chunks.json"), [])
    total = len(windows)
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return jsonify({"error": "index 非法"}), 400
    if index < 0 or index >= total:
        return jsonify({"error": "index 越界"}), 400

    prog = get_progress(d)
    if index not in prog["splitDone"]:
        _split_one(d, time_id, index)
        prog = mark_done(d, prog, "splitDone", index)

    block_count = len(read_json(os.path.join(d, "split.json"), []))
    return jsonify({"ok": True, "processed": len(prog["splitDone"]),
                    "total": total, "blockCount": block_count,
                    "splitDone": prog["splitDone"]})


def _split_one(d, time_id, index):
    """对第 index 个窗口调用 API 分块。AI 只返回行号范围 [起,止]，由算法按全局行号从原文切分。
    通过 split_state.json 里的 seen 记录已输出的全局行号，用于跨窗口（含重叠部分）去重。"""
    config = get_config()
    windows = read_json(os.path.join(d, "chunks.json"), [])
    summary = read_text(os.path.join(d, "summary.md"))
    original = read_text(os.path.join(d, "original.txt"))
    lines = original_lines(original)

    split_file = os.path.join(d, "split.json")
    state_file = os.path.join(d, "split_state.json")
    blocks = read_json(split_file, [])
    seen = set(read_json(state_file, {"seen": []})["seen"])

    # 该窗口切为行：过滤纯空白片段，并只保留能在原文精确定位到的整行（排除跨窗口边界被切断的伪行）
    w_lines = [ln for ln in windows[index].split("\n")
               if ln.strip() != "" and find_line(lines, ln, 0) != -1]
    nums = number_blocks([w_lines], lines)[0]
    numbered = "\n".join("%d: %s" % (num, ln) for num, ln in zip(nums, w_lines))

    p = prompts.split_prompt(summary, numbered)
    content = chat(config, p["system"], p["user"])

    # AI 返回 [[起,止],...] 行号范围（闭区间）
    ranges = []
    for r in extract_json_list(content):
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            try:
                a, b = int(r[0]), int(r[1])
            except (TypeError, ValueError):
                continue
            if a > b:
                a, b = b, a
            ranges.append((a, b))
    ranges.sort()

    added = []
    for a, b in ranges:
        block_lines = []
        for num, ln in zip(nums, w_lines):
            if a <= num <= b and num not in seen:
                block_lines.append(ln)
                seen.add(num)
        if block_lines:
            added.append(block_lines)

    if added:
        blocks.extend(added)
        write_json(split_file, blocks)
    write_json(state_file, {"seen": sorted(seen)})
    return blocks


@app.route("/api/process/evaluate", methods=["POST"])
def api_evaluate():
    """第三次 API：对每个尚未评估的块做评估（幂等可续接）。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    blocks = read_json(os.path.join(d, "split.json"), [])
    prog = get_progress(d)
    for i in range(len(blocks)):
        if i in prog["evaluateDone"]:
            continue
        _evaluate_one(d, time_id, i)
        prog = mark_done(d, prog, "evaluateDone", i)
    count = len(read_json(os.path.join(d, "suggestion.json"), []))
    return jsonify({"ok": True, "processed": len(prog["evaluateDone"]),
                    "total": len(blocks), "count": count})


@app.route("/api/process/evaluate/step", methods=["POST"])
def api_evaluate_step():
    """循环（幂等）：评估第 index 个块，返回当前进度 {已处理}/{总数}。
    若该块已评估则跳过，供出错后【重试】续接进度。"""
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = ensure_time_dir(time_id)
    blocks = read_json(os.path.join(d, "split.json"), [])
    total = len(blocks)
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return jsonify({"error": "index 非法"}), 400
    if index < 0 or index >= total:
        return jsonify({"error": "index 越界"}), 400

    prog = get_progress(d)
    changed = 0
    if index not in prog["evaluateDone"]:
        changed = _evaluate_one(d, time_id, index)
        prog = mark_done(d, prog, "evaluateDone", index)

    count = len(read_json(os.path.join(d, "suggestion.json"), []))
    return jsonify({"ok": True, "processed": len(prog["evaluateDone"]),
                    "total": total, "count": count,
                    "newItems": changed, "evaluateDone": prog["evaluateDone"]})


def _evaluate_one(d, time_id, index):
    """对第 index 个块调用 API 评估，追加写入 suggestion.json，返回新增条数。"""
    config = get_config()
    blocks = read_json(os.path.join(d, "split.json"), [])
    summary = read_text(os.path.join(d, "summary.md"))
    original = read_text(os.path.join(d, "original.txt"))
    lines = original_lines(original)
    block = blocks[index]

    # 计算该块每一行的全局行号
    all_nums = number_blocks(blocks, lines)
    nums = all_nums[index]
    numbered = "\n".join("%d: %s" % (num, line) for num, line in zip(nums, block))

    p = prompts.evaluate_prompt(summary, numbered)
    content = chat(config, p["system"], p["user"])
    results = [r for r in extract_json_list(content)
               if isinstance(r, dict) and (r.get("original") or r.get("line")) and r.get("issue") and r.get("suggested")]

    suggestions = read_json(os.path.join(d, "suggestion.json"), [])
    added = 0
    for r in results:
        suggestions.append({
            "id": "b%d-l%s" % (index, r.get("line")),
            "blockIndex": index,
            "line": int(r.get("line") or nums[0]),
            "original": str(r.get("original") or ""),
            "issue": str(r.get("issue") or ""),
            "suggested": str(r.get("suggested") or ""),
            "userAffirm": "",
        })
        added += 1
    write_json(os.path.join(d, "suggestion.json"), suggestions)
    return added


@app.route("/api/process/status", methods=["GET"])
def api_status():
    """返回某次运行的完整处理进度，供前端重试续接与历史记录继续使用。"""
    time_id = request.args.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = run_dir(time_id)
    if not os.path.exists(d):
        return jsonify({"error": "结果不存在"}), 404
    prog = get_progress(d)
    windows = read_json(os.path.join(d, "chunks.json"), [])
    return jsonify({
        "time": time_id,
        "chunkTotal": len(windows),
        "summaryDone": prog["summaryDone"],
        "splitDone": prog["splitDone"],
        "evaluateDone": prog["evaluateDone"],
        "splitBlockCount": len(read_json(os.path.join(d, "split.json"), [])),
        "evaluateCount": len(read_json(os.path.join(d, "suggestion.json"), [])),
        "summary": read_text(os.path.join(d, "summary.md")),
    })


@app.route("/api/history", methods=["GET"])
def api_history():
    """列出所有历史运行记录（按时间倒序），供选择后继续处理进度。"""
    entries = []
    if os.path.isdir(DATA_DIR):
        for name in sorted(os.listdir(DATA_DIR), reverse=True):
            dd = os.path.join(DATA_DIR, name)
            if not os.path.isdir(dd):
                continue
            if not os.path.exists(os.path.join(dd, "original.txt")):
                continue
            meta = read_json(os.path.join(dd, "meta.json"), {})
            prog = get_progress(dd)
            chunk_total = len(read_json(os.path.join(dd, "chunks.json"), []))
            split_block = len(read_json(os.path.join(dd, "split.json"), []))
            entries.append({
                "time": name,
                "title": meta.get("title", "") or name,
                "created": meta.get("created", name),
                "chunkTotal": chunk_total,
                "summaryDoneCount": len(prog["summaryDone"]),
                "splitDoneCount": len(prog["splitDone"]),
                "splitBlockCount": split_block,
                "evaluateDoneCount": len(prog["evaluateDone"]),
            })
    return jsonify(entries)


@app.route("/api/result", methods=["GET"])
def api_result():
    time_id = request.args.get("time")
    if not time_id:
        return jsonify({"error": "缺少 time"}), 400
    d = run_dir(time_id)
    if not os.path.exists(d):
        return jsonify({"error": "结果不存在"}), 404
    original = read_text(os.path.join(d, "original.txt"))
    summary = read_text(os.path.join(d, "summary.md"))
    split = read_json(os.path.join(d, "split.json"), [])
    suggestions = read_json(os.path.join(d, "suggestion.json"), [])
    return jsonify({"time": time_id, "original": original, "summary": summary,
                    "split": split, "suggestions": suggestions})


@app.route("/api/affirm", methods=["POST"])
def api_affirm():
    body = request.get_json(force=True, silent=True) or {}
    time_id = body.get("time")
    item_id = body.get("id")
    if not time_id or not item_id:
        return jsonify({"error": "缺少 time/id"}), 400
    d = run_dir(time_id)
    file_path = os.path.join(d, "suggestion.json")
    items = read_json(file_path, [])
    idx = next((i for i, s in enumerate(items) if s.get("id") == item_id), -1)
    if idx == -1:
        return jsonify({"error": "未找到该项"}), 404
    items[idx]["userAffirm"] = str(body.get("userAffirm") or "")
    write_json(file_path, items)
    return jsonify({"ok": True, "item": items[idx]})


if __name__ == "__main__":
    ensure_data_dir()
    print("Novel Review (Python) server running: http://localhost:%d" % PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)