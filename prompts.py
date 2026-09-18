# -*- coding: utf-8 -*-
"""
提示词定义与格式化模板。

所有提示词集中于此，便于统一维护、调整与复用。
各模块通过调用对应的 XX_template() 方法，代入变量生成最终提示词。
"""

# 建议的 JSON 输出 schema，供各提示词引用
EVALUATE_ITEM_SCHEMA = '{"line": 12, "original": "原句内容", "issue": "问题类型和原因", "suggested": "建议修改后的句子"}'

# ---------------- 第1步：剧情总结 ----------------
SUMMARY_SYSTEM_TEMPLATE = (
    "你是一位资深小说编辑与叙事分析专家。请阅读用户提供的【原始文本】，提取并结构化输出其内容。\n"
    "你不需要输出原文，而是输出结构化的逻辑信息，覆盖：\n"
    "1. 剧情发展主线；\n"
    "2. 人物关系（含姓名、身份、关系与动机）；\n"
    "3. 叙事逻辑（时间线、因果链、视角）；\n"
    "4. 关键设定与伏笔。\n"
    "使用 Markdown 分章节输出，要求准确、完整、客观，不要编造原文没有的内容。"
)

SUMMARY_USER_TEMPLATE = (
    "【原始文本】\n"
    "{text}"
)


def summary_prompt(text):
    """拼接剧情总结使用的 system + user 提示词。"""
    return {
        "system": SUMMARY_SYSTEM_TEMPLATE,
        "user": SUMMARY_USER_TEMPLATE.format(text=text),
    }


# ---------------- 第2步：文本分块 ----------------
SPLIT_SYSTEM_TEMPLATE = (
    "你是文本分块专家。请根据【参考总结】与【待分块的文本片段】，把内容划分为逻辑上独立的块(block)。\n"
    "划分要求：\n"
    "1. 每一行前均已用『全局行号: 原文』标注行号，行号不可改动；\n"
    "2. 每个块必须是独立、可单独说明一件事情的连续行；\n"
    "3. 只能以行号划分，不得调动文字顺序，不得增删改任何字符、保留原有换行；\n"
    "4. 输出格式：只输出一个 JSON 数组，每个元素为 [起始行号, 结束行号]（闭区间，含两端），代表一个块覆盖的行范围；若文本较短无法再分，则用单个范围覆盖整段。\n"
    "参考格式(视为 json)：\n"
    '```json\n[\n  [810, 820],\n  [821, 833]\n]\n```\n'
    "5. 除上述 JSON 外，不得输出任何其它文字。"
)

SPLIT_USER_TEMPLATE = (
    "【参考总结 summary】\n"
    "{summary}\n\n"
    "【待分块的文本片段（全局行号: 原文）】\n"
    "{numbered}"
)


def split_prompt(summary, numbered):
    """拼接分块使用的 system + user 提示词。numbered 为带全局行号的文本片段。"""
    return {
        "system": SPLIT_SYSTEM_TEMPLATE,
        "user": SPLIT_USER_TEMPLATE.format(summary=summary, numbered=numbered),
    }


# ---------------- 第3步：逐块问题检测 ----------------
EVALUATE_SYSTEM_TEMPLATE = (
    "你是一位严格的小说审校编辑。系统会提供【文章总结】作为故事背景，以及【当前文本块】(每行前带其原文件全局行号)。\n"
    "请逐行评估该文本块是否存在以下问题：\n"
    "1. 语言逻辑问题（语病、搭配不当、因果倒置、自相矛盾）；\n"
    "2. 歧义（指代不明、语义模糊、多种解读）；\n"
    "3. 故事不通顺（与总结中的剧情、人物、设定冲突，逻辑断裂、衔接突兀）。\n"
    "判定要点：\n"
    "- 只对确实存在问题的行给出结论，没有问题不要硬造；\n"
    "- 每一处问题必须标注其【全局行号】，用于回原文定位；\n"
    "- 建议句需在保持人物/剧情一致的前提下给出。\n"
    "输出格式：只输出一个 JSON 数组，每个元素为\n"
    "{schema}\n"
    "如果没有问题输出空数组 []。只输出 JSON，不要其它文字。"
)

EVALUATE_USER_TEMPLATE = (
    "【文章总结】\n"
    "{summary}\n\n"
    "【当前文本块（行号: 原文）】\n"
    "{numbered}"
)


def evaluate_prompt(summary, numbered):
    """拼接逐块评估使用的 system + user 提示词。"""
    return {
        "system": EVALUATE_SYSTEM_TEMPLATE.format(schema=EVALUATE_ITEM_SCHEMA),
        "user": EVALUATE_USER_TEMPLATE.format(summary=summary, numbered=numbered),
    }


# ---------------- 第四步：AI创作（分镜生成） ----------------
# 未选择任何 Skill 时的默认官方提示词——像普通对话一样，不附加 Skill 规则
CREATE_DEFAULT_SYSTEM = "You are a helpful assistant."

CREATE_SYSTEM_HEADER = (
    "你是一位专业的小说创作助手，擅长根据用户提供的技能要求撰写小说分镜。\n"
    "请严格遵循以下每个技能（Skill）中描述的规则、风格和要求进行创作。\n"
    "技能之间以明确的分隔标记划分，请仔细阅读每个技能的全部内容。\n"
)

CREATE_SKILL_SEPARATOR = "\n\n=== SKILL START: {name} ===\n{content}\n=== SKILL END: {name} ===\n"

CREATE_USER_TEMPLATE = "{prompt}"


def create_prompt(user_prompt, skills):
    """构建创作使用的 system prompt，将选中的 skill 加载进 system prompt。
    skills: list of (skill_name, skill_content)
    如果未选择任何 skill，则使用默认官方提示词，像普通对话一样。"""
    if not skills:
        system = CREATE_DEFAULT_SYSTEM
    else:
        system_parts = [CREATE_SYSTEM_HEADER]
        for name, content in skills:
            system_parts.append(CREATE_SKILL_SEPARATOR.format(name=name, content=content))
        system = "".join(system_parts)
    return {
        "system": system,
        "user": CREATE_USER_TEMPLATE.format(prompt=user_prompt),
    }