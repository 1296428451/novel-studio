<p align="center">
  <h1 align="center">📖 AI 文章逻辑审核助手</h1>
  <p align="center">
    基于大语言模型的 <strong>长篇小说 / 长文逻辑审校</strong> 工具<br/>
    自动检测语句逻辑、文本歧义、剧情不通顺，并给出修改建议
  </p>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white">
  <img alt="OpenAI Compatible" src="https://img.shields.io/badge/API-OpenAI%20Compatible-412991">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-yellow">
</p>

---

## ✨ 功能特性

- **AI 逻辑审校**：调用任意 OpenAI 兼容接口（GPT / Claude / Qwen / 私有部署均可，目前测试Qwen 3.5 27B 即可达到审核效果），对文章进行**语句逻辑、歧义、故事不通顺**三类问题的自动检测
- **三阶段流水线**：`剧情总结 → 按行号分块 → 逐块问题检测`，每阶段独立、可续接
- **超长文本支持**：超过 5000 字自动切窗（3000 字一组、相邻交叉 500 字），突破上下文长度限制
- **按行号精确切分**：分块阶段 AI 只返回行号范围 `[起,止]`，由算法从原文切分，**不增删改任何原文字符**
- **断点续传**：任一步请求超时/出错时，点【重试】即从当前进度继续，已完成的窗口/块不重复消耗
- **历史记录**：可随时选择之前的任务继续处理
- **思考模型兼容**：自动剥离 `<thinking>`/`<reasoning>` 内容与 HTML 残留，鲁棒解析 JSON
- **人工复核界面**：逐条查看问题句 + AI 建议，可修改并保存最终表述（`userAffirm`）
- **配置灵活**：Base URL / API Key / 模型名在网页上填写，支持代理与私有化部署，Key 仅存本机

---

## 🧭 项目结构

```
novel-review-python/
├── main.py            # Flask 后端：HTTP 服务 + 全部 API（端口默认 18000）
├── prompts.py         # 提示词模板（总结 / 分块 / 逐块检测），独立维护
├── requirements.txt   # 依赖：flask、requests
├── public/            # 前端静态页面
│   ├── index.html     # 主界面：粘贴原文、处理进度、历史记录
│   ├── review.html    # 审核确认页：逐条校订
│   ├── config.html    # API 配置页
│   ├── api.js         # 前端安全 JSON 解析器
│   └── style.css      # 样式
└── data/              # 运行时生成（不随仓库提交）
    ├── config.json                  # API 配置
    └── {time}/                      # 每次任务的产物（time 为按时间戳生成的会话编号）
        ├── original.txt             # 原始文本
        ├── chunks.json              # 拆分后的窗口
        ├── summaries.json           # 各窗口总结（逐窗口落盘，可续接）
        ├── summary.md               # 合并后的剧情总结
        ├── split.json               # 分块结果（每块为原文整行数组）
        ├── split_state.json         # 分块全局行号去重状态
        ├── suggestion.json          # 检测出的问题句 + AI 建议
        ├── progress.json            # 处理进度（断点续传依据）
        └── meta.json                # 任务元信息（标题、时间）
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+（推荐 3.10+）

### 2. 安装依赖

```bash
cd novel-review-python
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

1. 进入 **API 配置** 页，填写 Base URL / API Key / 模型名后保存
2. 回到 **主界面**，粘贴文章原文，点击「开始审核」
3. 观察三阶段进度条（总结 → 分块 → 逐块检测），完成后跳转「审核确认」页逐条校订

---

## 🔄 处理流程

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
审核确认 · 逐条校订       人工复核 AI 建议，保存最终表述
```

**请求量估算**：总请求数 = `2 × 窗口数 + 分块数`。短文本（≤5000 字）通常为 `3` 次（总结 1 + 分块 1 + 检测 1）；10 个窗口、15 个块则为 `2×10+15 = 35` 次。

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

### 断点续传与历史

每次任务进度写入 `progress.json`（已完成的总结窗口 / 分块窗口 / 评估块索引）。所有 `*/step` 接口**幂等**：已完成索引直接跳过。出错后点【重试】或从历史记录选择该任务，都会从 `/api/process/status` 重新计算剩余部分并继续，绝不重复请求已完成单元。

### 思考模型与异常兼容

- 自动剥离模型输出的 `<thinking>`/`<reasoning>` 块（连同内部内容）与残留 HTML 标签，避免干扰 JSON 提取
- 后端所有 404 / 405 / 500 错误统一返回 JSON；前端使用安全解析器，遇到非 JSON 响应给出可读提示而非报错

---

## 🔌 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/config` | 读取 / 保存 API 配置 |
| POST | `/api/process/start` | 创建任务会话（存原文、切窗），返回 `chunkTotal` |
| POST | `/api/process/summary` | 对全部未总结窗口生成剧情总结（幂等） |
| POST | `/api/process/summary/step` | 对第 `index` 窗口生成总结，返回进度 |
| POST | `/api/process/split` | 对全部未分块窗口分块（幂等） |
| POST | `/api/process/split/step` | 对第 `index` 窗口按行号分块，返回进度 |
| POST | `/api/process/evaluate` | 对全部未评估块进行检测（幂等） |
| POST | `/api/process/evaluate/step` | 评估第 `index` 个块，返回进度 |
| GET | `/api/process/status?time=` | 返回某任务完整处理进度（续接依据） |
| GET | `/api/history` | 列出全部历史任务 |
| GET | `/api/result?time=` | 取回某任务全部产物 |
| POST | `/api/affirm` | 更新某条问题的最终表述 `userAffirm` |

---

## ⚙️ 配置参数

关键常量定义在 `main.py` 顶部，也可按需修改：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `18000` | 服务端口（可用环境变量覆盖） |
| `CHUNK_LIMIT` | `5000` | 超过该字数必须拆窗 |
| `CHUNK_SIZE` | `3000` | 每个窗口字数 |
| `CHUNK_OVERLAP` | `500` | 相邻窗口交叉字数 |

提示词模板集中在 `prompts.py`，可独立调整总结 / 分块 / 检测的判定标准与输出结构，无需改动主逻辑。

---

## 📄 LICENSE

[MIT](LICENSE)

> 本工具调用第三方大模型 API，实际审校质量取决于所选模型。请遵守所用 API 服务商的条款，并注意数据隐私。