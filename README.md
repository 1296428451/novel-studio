<p align="center">
  <h1 align="center">📖 小说创作助手</h1>
  <p align="center">
    纯 Python + Flask 的<strong>长篇小说工作台</strong><br/>
    <strong>逻辑审校</strong> 与 <strong>AI 分镜创作</strong> 双模块一体，共用一套 OpenAI 兼容接口配置
  </p>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white">
  <img alt="OpenAI Compatible" src="https://img.shields.io/badge/API-OpenAI%20Compatible-412991">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-yellow">
</p>

---

## ✨ 功能总览

三个模块，四个页面，一个进程：

| 模块 | 页面 | 做什么 |
|---|---|---|
| **审校** | `index.html` → `review.html` | 长文三阶段自动审校，逐条人工复核并保存最终表述 |
| **创作** | `create.html` | 选择 Skill、输入需求，AI 流式生成小说分镜 |
| **配置** | `config.html` | 填写 Base URL / API Key / 模型名，可在线拉取模型列表 |

---

## 🔍 模块一 · 长文审校

- **AI 逻辑审校**：调用任意 OpenAI 兼容接口（GPT / Claude / Qwen / 私有部署均可，实测 Qwen 系列 27B 级别即可满足审校需求），对文章进行**语句逻辑、文本歧义、剧情不通顺**三类问题的自动检测
- **三阶段流水线**：`剧情总结 → 按行号分块 → 逐块问题检测`，每阶段独立、可续接
- **超长文本支持**：超过 5000 字自动切窗（3000 字一组、相邻交叉 500 字），突破上下文长度限制
- **按行号精确切分**：分块阶段 AI 只返回行号范围 `[起,止]`，由算法从原文切分，**不增删改任何原文字符**
- **断点续传**：任一步请求超时/出错时，点【重试】即从当前进度继续，已完成的窗口/块不重复消耗
- **历史记录**：可随时选择之前的任务继续处理，或直接删除
- **人工复核界面**：逐条查看问题句 + AI 原因 + AI 建议，可修改并保存最终表述（`userAffirm`）

---

## ✍️ 模块二 · AI 创作（分镜生成）

- **Skill 驱动创作**：把选中的 Skill 全文注入 system prompt，AI 按 Skill 中定义的规则与风格撰写分镜
- **SSE 流式输出**：后端逐段透传增量，前端边生成边渲染 Markdown，长文创作不必干等
- **创作历史**：每次生成均落盘需求、所选 Skill 与产出；生成失败也会留档并记录失败原因，可回看或删除
- **图片级兼容**：自动识别并尝试还原上游返回的乱码（详见下文「稳定性与异常兜底」）

> 💡 **Skill 使用建议**：Skill 不是加载越多越好，多了容易“降智”，少了容易需求不足。推荐选择 **1-2 个**，总长度不超过 2 万字。

---

## 🗂️ 模块三 · Skill 管理

在创作页内直接完成 Skill 的全生命周期维护，文件统一存放在项目根的 `skill/` 目录：

- 列表 / 多选（勾选状态按文件名缓存在浏览器本地）
- 上传（`.txt` / `.md`，统一转为 `.txt` 落盘）
- 重命名
- 在线编辑并保存
- 删除

---

## 🧭 项目结构

```
novel-studio/
├── main.py            # 应用入口：Flask 实例、页面路由、/api/config、/api/models、启动
├── api_review.py      # 审校流程 API（Blueprint: review）
├── api_create.py      # AI 创作 API（Blueprint: create，SSE 流式）
├── api_skills.py      # Skill 管理 API（Blueprint: skills）
├── utils.py           # 底层工具：文件读写 / 进度持久化 / 切窗 / 行号 / 上游调用
├── prompts.py         # 全部提示词模板（总结 / 分块 / 检测 / 创作），独立维护
├── errors.py          # 全局错误处理：统一返回 JSON
├── requirements.txt   # 依赖：flask、requests
├── public/            # 前端静态页面
│   ├── index.html     # 审校主界面：粘贴原文、处理进度、审校历史
│   ├── review.html    # 审校确认页：逐条校订
│   ├── create.html    # 创作页：Skill 选择 / 管理、流式输出、创作历史
│   ├── config.html    # API 配置页
│   ├── api.js         # 前端安全 JSON 解析器
│   ├── lib/marked.min.js
│   └── style.css      # 样式
├── skill/             # Skill 文本库（.txt / .md），创作时注入 system prompt
└── data/              # 运行时生成（不随仓库提交，见 .gitignore）
    ├── config.json                  # API 配置
    ├── review/{time}/               # 审校任务产物（time 为按时间戳生成的会话编号）
    │   ├── original.txt             # 原始文本
    │   ├── chunks.json              # 拆分后的窗口
    │   ├── summaries.json           # 各窗口总结（逐窗口落盘，可续接）
    │   ├── summary.md               # 合并后的剧情总结
    │   ├── split.json               # 分块结果（每块为原文整行数组）
    │   ├── split_state.json         # 分块全局行号去重状态
    │   ├── suggestion.json          # 检测出的问题句 + AI 建议 + userAffirm
    │   ├── progress.json            # 处理进度（断点续传依据）
    │   └── meta.json                # 任务元信息（标题、时间）
    └── create/{time}/               # 创作任务产物
        ├── input.json               # 创作需求、所选 Skill、实际 system prompt
        ├── output.txt               # 生成结果（清洗后全文）
        └── error.json               # 生成失败时的错误记录（成功时不存在）
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+（推荐 3.10+）

### 2. 安装依赖

```bash
cd novel-studio
pip install -r requirements.txt

# 或使用虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. 启动服务

```bash
python main.py
# 默认监听 18000 端口，可用环境变量修改
# PORT=9000 python main.py
```

### 4. 打开页面

浏览器访问 **http://localhost:18000**

**走审校：**

1. 进入 **API 配置** 页，填写 Base URL / API Key / 模型名后保存
2. 回到 **审校** 页，粘贴文章原文，点击「开始审核」
3. 观察三阶段进度条（总结 → 分块 → 逐块检测），完成后跳转 **审校确认** 页逐条校订

**走创作：**

1. 进入 **创作** 页，勾选 1-2 个 Skill（首次使用可先上传 `.txt` / `.md`）
2. 输入创作需求，点击「开始生成」，结果流式出现在下方
3. 生成记录进入 **创作历史**，可随时回看或删除

---

## 🔄 处理流程

### 审校流程

```
原文 
  │  ➜ 超过 5000 字自动切窗（3000 字/组，交叉 500 字）
  ▼
阶段1 · 剧情总结         每个窗口生成总结 → 合并为 summary.md      （每次请求 = 一个窗口）
  ▼
阶段2 · 按行号分块       AI 返回行号范围[起,止]，算法从原文切块      （每次请求 = 一个窗口）
  ▼
阶段3 · 逐块问题检测      依据 summary 检测语病/歧义/剧情不通顺       （每次请求 = 一个块）
  ▼
审校确认 · 逐条校订       人工复核 AI 建议，保存最终表述
```

**请求量估算**：总请求数 = `2 × 窗口数 + 分块数`。短文本（≤5000 字）通常为 `3` 次（总结 1 + 分块 1 + 检测 1）；10 个窗口、15 个块则为 `2×10+15 = 35` 次。

### 创作流程

```
选定 Skill（1-2 个）+ 创作需求
  │  ➜ Skill 全文以 === SKILL START/END === 分隔拼入 system prompt
  ▼
POST /api/create/generate
  │  ➜ 先落盘 input.json（需求 + Skill + system prompt），中途失败也有记录
  ▼
SSE 流式透传  meta → delta → delta … → done
  │  ➜ 前端边收边渲染 Markdown，并显示已等待时长
  ▼
清洗后写入 output.txt，前端以落盘版本为准
```

---

## 🧠 核心设计

### 按行号切分，保证原文零改动

分块阶段给模型提供带**全局行号**的片段（`行号: 原文`），模型只需返回行号范围：

```
【待分块的文本片段（全局行号: 原文）】
810: 他推门走进房间。
811: 房间里很昏暗。
812: 她坐在窗边没有说话。
```

模型响应（JSON）：

```json
[
  [810, 820],
  [821, 833]
]
```

算法据此从 `original.txt` 中精确切出整行，不增删改任何字符，并通过 `split_state.json` 对跨窗口重叠部分做**全局行号去重**。

### Skill 注入 system prompt

创作时每个 Skill 被包进明确的分隔标记，既保证边界清晰，也便于模型区分多个 Skill 的职责：

```
你是一位专业的小说创作助手……
=== SKILL START: 网文爽文节奏（测试） ===
（Skill 全文）
=== SKILL END: 网文爽文节奏（测试） ===
```

用户消息区只放创作需求本身，不额外加“请生成”这类前缀。

### 断点续传与幂等

审校的每次任务进度写入 `progress.json`（已完成的总结窗口 / 分块窗口 / 评估块索引）。所有 `*/step` 接口**幂等**：已完成索引直接跳过。出错后点【重试】或从历史记录选择该任务，都会从 `/api/process/status` 重新计算剩余部分并继续，绝不重复请求已完成单元。

---

## 🔌 API 端点

**页面**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 审校主界面 |
| GET | `/<path:name>` | `public/` 下任意静态资源 |

**配置**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/config` | 读取 / 保存 API 配置（baseUrl、apiKey、model） |
| GET | `/api/models` | 代理上游 `models` 接口，返回可用模型名列表 |

**审校**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/process/start` | 创建任务会话（存原文、切窗），返回 `chunkTotal` |
| POST | `/api/process/summary` | 对全部未总结窗口生成剧情总结（幂等） |
| POST | `/api/process/summary/step` | 对第 `index` 窗口生成总结，返回进度 |
| POST | `/api/process/split` | 对全部未分块窗口分块（幂等） |
| POST | `/api/process/split/step` | 对第 `index` 窗口按行号分块，返回进度 |
| POST | `/api/process/evaluate` | 对全部未评估块进行检测（幂等） |
| POST | `/api/process/evaluate/step` | 评估第 `index` 个块，返回进度 |
| GET | `/api/process/status?time=` | 返回某任务完整处理进度（续接依据） |
| GET | `/api/history` | 列出全部审校任务 |
| DELETE | `/api/history?time=` | 删除某条审校任务 |
| GET | `/api/result?time=` | 取回某任务全部产物 |
| POST | `/api/affirm` | 更新某条问题的最终表述 `userAffirm` |

**创作**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/create/generate` | 发起生成，返回 `text/event-stream`（事件：`meta` / `delta` / `done` / `error`） |
| GET | `/api/create/history` | 列出全部创作任务（需求、Skill、是否产出、失败原因） |
| DELETE | `/api/create/history?time=` | 删除某条创作记录 |
| GET | `/api/create/result?time=` | 取回某次创作的需求与产出 |

**Skill**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills/list` | 列出 `skill/` 下的 `.txt` / `.md` |
| POST | `/api/skills/content` | 批量取多个 Skill 的正文 |
| GET | `/api/skills/read?name=` | 读取单个 Skill 正文 |
| POST | `/api/skills/save` | 保存（新建/覆盖）Skill |
| POST | `/api/skills/upload` | 上传 Skill 文件（`multipart/form-data`） |
| POST | `/api/skills/rename` | 重命名 Skill |
| DELETE | `/api/skills/delete?name=` | 删除 Skill |

---

## ⚙️ 配置参数

关键常量定义在 `utils.py` 顶部，也可按需修改：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `18000` | 服务端口（环境变量可覆盖） |
| `CHUNK_LIMIT` | `5000` | 超过该字数必须拆窗 |
| `CHUNK_SIZE` | `3000` | 每个窗口字数 |
| `CHUNK_OVERLAP` | `500` | 相邻窗口交叉字数 |
| `CHAT_CONNECT_TIMEOUT` | `20` | 上游连接超时（秒） |
| `CHAT_READ_TIMEOUT` | `1800` | 上游读超时（秒，按「连续无数据」计时） |
| `REPEAT_CHECK_LEN` | `100` | 尾部重复检测长度（连续该长度字符相同即中断） |
| `temperature` | `0.3` | 请求上游时的采样温度 |

提示词模板集中在 `prompts.py`，可独立调整总结 / 分块 / 检测 / 创作的判定标准与输出结构，无需改动业务逻辑。

---

## 🛡️ 稳定性与异常兜底

面向真实网络环境与“不听话”的模型，做了几层防护：

| 场景 | 处理方式 |
|---|---|
| 模型输出 `<thinking>` / `<reasoning>` | 连同内部内容整体剥离，并清除残留 HTML 标签与代码围栏，保证 JSON 可解析 |
| 模型陷入重复输出 | 流式过程中每积累 100 字符检查一次尾部，连续相同即主动中断并报错 |
| 上游流被掐断 / 长时间无数据 | 转成带 `retryable` 标记的错误，前端可据此提示是否值得重试 |
| 上游返回的 UTF-8 被按 Latin-1 解码 | `recover_mojibake()` 尝试还原为正确中文，读取结果时自动应用 |
| 上游未按 SSE 返回 | 自动降级为整体读取 JSON，一次性输出全文 |
| 404 / 405 / 500 | 后端统一返回 JSON，前端 `api.js` 识别 HTML 响应并给出可读提示，而非抛出解析异常 |
| 请求悬挂 | 前端看门狗：审校单步最长等待 40 分钟；创作连续 5 分钟收不到任何数据即中止 |

---

## 📄 LICENSE

MIT

> 本工具调用第三方大模型 API，实际审校与创作质量取决于所选模型与 Skill。请遵守所用 API 服务商的条款，并注意数据隐私。
