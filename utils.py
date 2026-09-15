# -*- coding: utf-8 -*-
"""工具模块：文件读写、进度管理、文本处理、AI 调用等底层逻辑。"""
import os
import re
import json
import time
import shutil

import requests

import prompts

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_ROOT, "data")
REVIEW_DATA_DIR = os.path.join(DATA_DIR, "review")
CREATE_DATA_DIR = os.path.join(DATA_DIR, "create")
SKILL_DIR = os.path.join(APP_ROOT, "skill")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

CHUNK_LIMIT = 5000
CHUNK_SIZE = 3000
CHUNK_OVERLAP = 500

# 上游 API 超时配置。读超时按「连续无数据」计时（非总时长），
# 长文分镜这类输出耗时很长，600s 偏紧，容易在中途被误判超时。
CHAT_CONNECT_TIMEOUT = 20
CHAT_READ_TIMEOUT = 1800


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
    return os.path.join(REVIEW_DATA_DIR, time_id)


def ensure_time_dir(time_id):
    d = run_dir(time_id)
    os.makedirs(d, exist_ok=True)
    return d


def create_run_dir(time_id):
    return os.path.join(CREATE_DATA_DIR, time_id)


def ensure_create_time_dir(time_id):
    d = create_run_dir(time_id)
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


def read_text(file_path, fallback=""):
    if not os.path.exists(file_path):
        return fallback
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def recover_mojibake(text):
    """当上游 API 返回的 UTF-8 字节被错误地按 Latin-1 解码时，
    输出文件会保存为乱码。本函数尝试将乱码还原为正确的中文。
    原理：乱码字符串 encode('latin-1') 可还原出原始 UTF-8 字节，
    再 decode('utf-8') 即可得到正确文本。
    """
    if not text or not isinstance(text, str):
        return text
    try:
        recovered = text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text
    cjk_original = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    cjk_recovered = sum(1 for c in recovered if "\u4e00" <= c <= "\u9fff")
    if cjk_recovered > cjk_original:
        return recovered
    return text


def ensure_data_layout():
    """启动时确保数据目录结构存在。"""
    ensure_data_dir()
    os.makedirs(REVIEW_DATA_DIR, exist_ok=True)
    os.makedirs(CREATE_DATA_DIR, exist_ok=True)


def migrate_legacy_review_data():
    """旧版审核数据存放在 data/{time}/，一次性迁移到 data/review/{time}/。"""
    if not os.path.isdir(DATA_DIR):
        return
    for name in os.listdir(DATA_DIR):
        src = os.path.join(DATA_DIR, name)
        if not os.path.isdir(src) or name in ("review", "create"):
            continue
        if os.path.exists(os.path.join(src, "original.txt")):
            dst = os.path.join(REVIEW_DATA_DIR, name)
            if not os.path.exists(dst):
                shutil.move(src, dst)


# ---------------- 处理进度持久化 ----------------
def get_progress(d):
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
    done = set(prog.get(key, []))
    done.add(int(index))
    prog[key] = sorted(done)
    save_progress(d, prog)
    return prog


# ---------------- 长文本窗口拆分 ----------------
def chunk_windows(text, limit=CHUNK_LIMIT, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
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
    for i in range(from_idx, len(lines)):
        if lines[i] == target:
            return i
    return -1


def number_blocks(blocks, lines):
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
                nums.append(ptr)
        out.append(nums)
    return out


# ---------------- OpenAI 兼容接口调用 ----------------
def _extract_text_from_content(content):
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
    content = _extract_text_from_content(message.get("content"))
    if content and "<!doctype" not in content.lower() and content.strip():
        return content
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
    body = str(text or "")
    body = re.sub(r"<\s*thinking[^>]*>[\s\S]{0,20000}?</\s*thinking\s*>", "", body, flags=re.I)
    body = re.sub(r"<\s*reasoning[^>]*>[\s\S]{0,20000}?</\s*reasoning\s*>", "", body, flags=re.I)
    body = re.sub(r"<\s*/\s*?thinking>", "", body, flags=re.I)
    body = re.sub(r"<\s*thinking[^>]*>", "", body, flags=re.I)
    body = re.sub(r"<\s*/\s*?reasoning>", "", body, flags=re.I)
    body = re.sub(r"<\s*reasoning[^>]*>", "", body, flags=re.I)
    body = re.sub(r"<[^>]{1,200}>", "", body)
    body = re.sub(r"```(?:json)?\s*", "", body, flags=re.I)
    body = body.replace("```", "")
    return body


REPEAT_CHECK_LEN = 100


class UpstreamError(RuntimeError):
    """上游 API 调用失败。http_status 用于告知前端该错误能否重试。"""

    def __init__(self, message, http_status=500):
        super().__init__(message)
        self.http_status = http_status


def _check_repeating_tail(text, length=REPEAT_CHECK_LEN):
    if len(text) < length:
        return None
    tail = text[-length:]
    if len(set(tail)) == 1:
        return tail[0]
    return None


def _clean_snippet(text, max_len=300):
    raw = (text or "")[:max_len]
    clean = re.sub(r"<[^>]*>", "", raw).strip()
    return clean if clean else "(无内容)"


def _open_chat_request(config, system_prompt, user_content):
    """向 OpenAI 兼容接口发起流式请求，返回 response。失败抛 UpstreamError。"""
    base_url = str(config.get("baseUrl") or "").strip()
    api_key = config.get("apiKey") or ""
    model = config.get("model") or ""
    if not base_url.endswith("/"):
        base_url += "/"
    endpoint = base_url + "chat/completions"

    payload = {
        "model": model,
        "temperature": 0.3,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    try:
        resp = requests.post(
            endpoint,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
            json=payload,
            timeout=(CHAT_CONNECT_TIMEOUT, CHAT_READ_TIMEOUT),
            stream=True,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectTimeout:
        raise UpstreamError(
            "连接上游 API 超时（%ds），请检查网络或 API 地址是否可访问" % CHAT_CONNECT_TIMEOUT, 504)
    except requests.exceptions.ReadTimeout:
        raise UpstreamError(
            "上游 API 长时间无数据返回（%d 秒），请求已中断，请稍后重试" % CHAT_READ_TIMEOUT, 504)
    except requests.exceptions.ConnectionError as e:
        raise UpstreamError("无法连接上游 API：" + str(e)[:200], 502)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        snippet = _clean_snippet(e.response.text) if e.response is not None else "(无响应)"
        if status in (429, 500, 502, 503, 504):
            raise UpstreamError("上游 API 返回 HTTP %s：%s" % (status, snippet), status)
        # 401/403/404 等属于配置类错误，重试没有意义
        raise UpstreamError("上游 API 返回 HTTP %s：%s" % (status, snippet), 400)
    except requests.exceptions.RequestException as e:
        raise UpstreamError("请求上游 API 异常：" + str(e)[:200], 502)
    return resp


def chat_stream(config, system_prompt, user_content):
    """流式调用上游 API：逐段 yield 文本增量，失败抛 UpstreamError。

    yield 出的增量是原始 content（未做 strip_reasoning），供前端实时显示；
    需要清洗后全文的场景由调用方聚合处理（见 chat()）。
    """
    resp = _open_chat_request(config, system_prompt, user_content)
    try:
        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            # 上游未按 SSE 返回：整体读取，一次性 yield 全文
            try:
                data = resp.json()
                message = data["choices"][0]["message"]
            except ValueError:
                raise UpstreamError(
                    "上游 API 返回非 JSON 格式（HTTP %s）：%s"
                    % (resp.status_code, _clean_snippet(resp.text)), 502
                )
            except (KeyError, IndexError, TypeError):
                raise UpstreamError("API 响应缺少 choices/message 字段：%s" % str(data)[:300], 502)
            yield _extract_message_text(message)
            return

        accumulated = []
        total_chars = 0
        last_checked = 0
        resp.encoding = "utf-8"
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].lstrip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"]
                except (KeyError, IndexError, TypeError):
                    continue
                content = _extract_text_from_content(delta.get("content"))
                if content:
                    accumulated.append(content)
                    total_chars += len(content)
                    yield content
                if total_chars - last_checked >= REPEAT_CHECK_LEN:
                    last_checked = total_chars
                    repeat_char = _check_repeating_tail("".join(accumulated))
                    if repeat_char is not None:
                        raise UpstreamError(
                            "模型输出异常：最近 %d 个字符完全相同（重复字符「%s」），已自动中断"
                            % (REPEAT_CHECK_LEN, repeat_char), 502)
        except requests.exceptions.ChunkedEncodingError as e:
            # 流在半途被上游掐断
            raise UpstreamError(
                "上游 API 流式响应中断（已接收 %d 字）：%s" % (total_chars, str(e)[:120]), 502)
        except requests.exceptions.ReadTimeout:
            raise UpstreamError(
                "上游 API 长时间无数据返回（%d 秒），已接收 %d 字，请求已中断"
                % (CHAT_READ_TIMEOUT, total_chars), 504)

        if not accumulated:
            raise UpstreamError("API 流式响应中未包含任何文本内容", 502)
    finally:
        resp.close()


def chat(config, system_prompt, user_content):
    """聚合式调用：内部复用 chat_stream，返回清洗后的全文。供审校流程使用。"""
    parts = list(chat_stream(config, system_prompt, user_content))
    text = strip_reasoning("".join(parts))
    if not text:
        raise UpstreamError("API 响应未包含任何文本内容", 502)
    return text


def extract_json_list(content):
    text = str(content or "").strip()
    text = strip_reasoning(text)
    if not text or text.lower().startswith("<!doctype") or "[" not in text:
        return []

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fenced.group(1) if fenced else text

    brace_start = candidate.find("[")
    brace_end = candidate.rfind("]")
    if brace_start != -1 and brace_end > brace_start:
        pass
    else:
        return []

    try:
        arr = json.loads(candidate[brace_start:brace_end + 1])
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


# ---------------- 审核处理逻辑 ----------------
def _summary_window(d, windows, index, config):
    p = prompts.summary_prompt(windows[index])
    return chat(config, p["system"], p["user"])


def _rebuild_summary_md(d, windows):
    summaries = read_json(os.path.join(d, "summaries.json"), {})
    ordered = [summaries.get(str(i), "").strip() for i in range(len(windows))]
    ordered = [s for s in ordered if s]
    summary = "\n\n---\n\n".join(ordered)
    with open(os.path.join(d, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    return summary


def _split_one(d, time_id, index):
    config = get_config()
    windows = read_json(os.path.join(d, "chunks.json"), [])
    summary = read_text(os.path.join(d, "summary.md"))
    original = read_text(os.path.join(d, "original.txt"))
    lines = original_lines(original)

    split_file = os.path.join(d, "split.json")
    state_file = os.path.join(d, "split_state.json")
    blocks = read_json(split_file, [])
    seen = set(read_json(state_file, {"seen": []})["seen"])

    w_lines = [ln for ln in windows[index].split("\n")
               if ln.strip() != "" and find_line(lines, ln, 0) != -1]
    nums = number_blocks([w_lines], lines)[0]
    numbered = "\n".join("%d: %s" % (num, ln) for num, ln in zip(nums, w_lines))

    p = prompts.split_prompt(summary, numbered)
    content = chat(config, p["system"], p["user"])

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


def _evaluate_one(d, time_id, index):
    config = get_config()
    blocks = read_json(os.path.join(d, "split.json"), [])
    summary = read_text(os.path.join(d, "summary.md"))
    original = read_text(os.path.join(d, "original.txt"))
    lines = original_lines(original)
    block = blocks[index]

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