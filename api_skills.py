# -*- coding: utf-8 -*-
"""Skill 管理 API：列表、读取、保存、上传、重命名、删除。"""
import os

from flask import Blueprint, jsonify, request

import utils

bp = Blueprint("skills", __name__)


def _body():
    return request.get_json(force=True, silent=True) or {}


def _err(msg, code=400):
    return jsonify({"error": msg}), code


@bp.route("/api/skills/list", methods=["GET"])
def api_skills_list():
    skills = []
    if os.path.isdir(utils.SKILL_DIR):
        for fname in sorted(os.listdir(utils.SKILL_DIR)):
            fpath = os.path.join(utils.SKILL_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if ext in (".txt", ".md"):
                    skills.append({
                        "name": fname,
                        "display": os.path.splitext(fname)[0],
                    })
    return jsonify(skills)


@bp.route("/api/skills/content", methods=["POST"])
def api_skills_content():
    names = _body().get("names", [])
    if not isinstance(names, list):
        return _err("names 必须是数组")
    result = {}
    for name in names:
        safe_name = os.path.basename(str(name))
        fpath = os.path.join(utils.SKILL_DIR, safe_name)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                result[name] = f.read()
        else:
            result[name] = ""
    return jsonify(result)


@bp.route("/api/skills/upload", methods=["POST"])
def api_skills_upload():
    if "file" not in request.files:
        return _err("请选择文件")
    f = request.files["file"]
    if not f.filename:
        return _err("文件名为空")
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".txt", ".md"):
        return _err("只支持 .txt 或 .md 文件")
    os.makedirs(utils.SKILL_DIR, exist_ok=True)
    save_name = os.path.splitext(f.filename)[0] + ".txt"
    f.save(os.path.join(utils.SKILL_DIR, save_name))
    return jsonify({"ok": True, "name": save_name})


@bp.route("/api/skills/rename", methods=["POST"])
def api_skills_rename():
    """重命名 skill 文件。"""
    body = _body()
    old = body.get("old", "")
    new = body.get("new", "")
    if not old or not new:
        return _err("缺少 old/new 参数")
    old_safe = os.path.basename(str(old))
    new_safe = os.path.basename(str(new))
    if not new_safe.endswith(".txt"):
        new_safe += ".txt"
    old_path = os.path.join(utils.SKILL_DIR, old_safe)
    new_path = os.path.join(utils.SKILL_DIR, new_safe)
    if not os.path.isfile(old_path):
        return _err("源文件不存在", 404)
    if os.path.exists(new_path):
        return _err("目标文件名已存在", 409)
    os.rename(old_path, new_path)
    return jsonify({"ok": True, "old": old_safe, "new": new_safe})


@bp.route("/api/skills/delete", methods=["DELETE"])
def api_skills_delete():
    name = request.args.get("name", "")
    if not name:
        return _err("缺少 name")
    safe_name = os.path.basename(str(name))
    fpath = os.path.join(utils.SKILL_DIR, safe_name)
    if os.path.isfile(fpath):
        os.remove(fpath)
        return jsonify({"ok": True, "name": safe_name})
    return _err("文件不存在", 404)


@bp.route("/api/skills/read", methods=["GET"])
def api_skills_read():
    name = request.args.get("name", "")
    if not name:
        return _err("缺少 name")
    safe_name = os.path.basename(str(name))
    fpath = os.path.join(utils.SKILL_DIR, safe_name)
    if os.path.isfile(fpath):
        with open(fpath, "r", encoding="utf-8") as f:
            return jsonify({"ok": True, "name": safe_name, "content": f.read()})
    return _err("文件不存在", 404)


@bp.route("/api/skills/save", methods=["POST"])
def api_skills_save():
    body = _body()
    name = body.get("name", "")
    if not name:
        return _err("缺少 name")
    safe_name = os.path.basename(str(name))
    fpath = os.path.join(utils.SKILL_DIR, safe_name)
    os.makedirs(utils.SKILL_DIR, exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(body.get("content", ""))
    return jsonify({"ok": True, "name": safe_name})
