# MemOS 记忆驱动的智能个人规划

 一个“会记住你”的个人规划助手原型，合并学习与办公两类场景为统一演示：在每轮规划前主动检索记忆（显式/隐式偏好、承诺、约束、任务/事实），生成结构化计划更新 JSON，写回记忆并复核冲突与承接，逐步形成个性化与跨周期的优化。

👉 新手入门教程：见 `tutorial.md`（从零到跑通）
👉 编码搭建教程：见 `coding_tutorial.md`（架构与模块拆分、接口与关键函数实现）

**为什么要记忆**
- 降低负担：避免重复描述偏好与历史任务，减少遗漏。
- 贯通周期：未完成事项自动承接，防止堆积与断裂。
- 更强个性化：结合“早晨深度工作/周末集中学习”等习惯与固定承诺。
- 可总结与解释：输出趋势与偏好更新、给出优先级裁决与来源说明。

**记忆类型（面向用户的口语表达）**
- 明确喜欢：用户直接表达的喜好（例：不想晚上学习）。
- 习惯倾向：从行为与完成率推断（例：周六上午最高效）。
- 固定安排：需避让的固定事件（例：09:30–10:00 晨会）。
- 限制/必须事项：非固定但会影响计划的条件（例：周三出差不可用）。
- 事项/任务：具体待办与事实（例：准备客户汇报 PPT、政治/英语学习任务）。

**术语与约定（规则解释）**
- `user_id`：唯一标识用户的字符串；所有记忆完全基于 `user_id` 隔离。若未显式提供，客户端在请求前自动生成并打印。
- 消息格式：写回与检索均围绕“对话消息列表”，形如 `[{"role": "user"|"assistant", "content": "..."}, ...]`。不要传 `conversation_id`。
- 检索约定：使用“用户当轮真实指令”作为检索 `query`，服务返回包含 `memory_detail_list` 与 `preference_detail_list` 的结果对象。
- 记忆列表展示：将 `memory_detail_list` 与 `preference_detail_list` 按“每元素一行”输出，dict/list 用 `json.dumps(..., ensure_ascii=false)` 保留结构，提升可读性。
- 计划更新 JSON：模型输出中的结构化计划需使用 `BEGIN_PLAN_UPDATE` 与 `END_PLAN_UPDATE` 包裹，以便稳定解析与写回；常用键名建议：
  - `today_slots`：当日候选时段与安排；
  - `commitments`：固定承诺列表；
  - `preferences`：偏好与趋势更新（显式/隐式）。
- 时间与格式：建议使用 `YYYY-MM-DDTHH:MM-HH:MM` 的区间格式（例：`2025-11-01T09:30-10:00`），便于冲突检测与承接；避免非标准时间表达导致解析失败。
- 冲突检测：以时间区间重叠为基础进行校验，输出“前移/后移并保留缓冲”的建议；未完成事项可进行 rollover（承接到下一时段/日期）。
- 环境变量约定：
  - 必需：`OPENAI_API_KEY`、`MEMOS_API_KEY`、`MEMOS_BASE_URL`；
  - 可选：`OPENAI_API_BASE`、`OPENAI_MODEL`、`MEMOS_VERIFY_SSL`（默认 true，可在受信网络下临时设为 false 排查证书问题）、`MEMOS_TIMEOUT`（默认 20 秒）。
- 网络稳健性：客户端已启用 `requests.Session` 重试（429/5xx）与显式 `Connection: close`，并支持可配置超时与 SSL 验证；仍异常时参考下文“网络与证书故障排除”。
- 容错策略：
  - 若计划 JSON 解析失败，不中断主流程，仅跳过“结构化写回”；
  - 键名与类型尽量保持一致性（字符串、列表、字典），避免因键名变更导致解析失败。

**统一演示（五轮高记忆难度）**
- 第 1 轮：基础规划并避冲突；早晨/午间轻任务；周末英语 3h；合理承接。
- 第 2 轮：复杂变更与偏好裁决（出差、牙医、合规培训、健身时间、客户汇报改档）。
- 第 3 轮：复盘与更新（将完成率低的任务顺延到后续、记录周末最高效时段为个人偏好、适配家庭活动）。
- 第 4 轮：别名混淆与互斥偏好裁决（“客户汇报”≈“季度回顾会”，新增家长会、健身改回 07:00 与早晨深度工作偏好冲突裁决）。
- 第 5 轮：跨周承接与去重（保留固定会议、去重改期、政治与英语分时交替、晚间避免高强度）。

**语言约定与术语简化**
- 面向用户的所有文本尽量使用纯中文，避免中英文夹杂。
- 术语更口语的表达建议：
  - “承诺”→“固定安排”；“约束”→“限制/必须事项”；
  - “显式偏好”→“明确喜欢”；“隐式偏好”→“习惯倾向”；
  - “事实/任务”→“事项/任务”。
- 示例文本统一中文时间表达（如“周六 09:00-12:00”），避免如“Saturday 9:00-12:00”的英文形式。
- 技术标记 `BEGIN_PLAN_UPDATE` / `END_PLAN_UPDATE` 保留用于解析稳定；如需完全中文化，可在开发中同步调整解析函数。

**运行与输出**
- 环境配置：
  - `.env` 设置 `OPENAI_API_KEY`、`MEMOS_API_KEY`、`MEMOS_BASE_URL`（可选：`OPENAI_API_BASE`、`OPENAI_MODEL`）。
  - 安装依赖：`pip install -r requirements.txt`
- 运行统一演示：
  - `python3 demo.py`
  - 不用显式传入 `user_id`：客户端在每次请求前确保存在 `user_id`；若不存在则随机生成一个并在控制台打印（基于 `user_id` 进行记忆隔离）。
- 控制台输出包含：
  - `📚 参考记忆条目`：逐行显示两类列表（每元素一行）：`memory_detail_list` 与 `preference_detail_list`；其他类型摘要按需展示。
  - `🗣️ 用户输入（完整）`：构建的 prompt 原文；`🗣️ 用户指令`：当轮补充要求。
  - `🤖 系统输出（完整）`：模型输出原文（可能包含 JSON）。
  - `🔧 计划更新 JSON（解析渲染）`：结构化更新指令，使用 `BEGIN_PLAN_UPDATE` / `END_PLAN_UPDATE` 包裹，便于解析。
  - `🧪 校验`：轻量时间重叠冲突检查；`🧠 复核摘要`：写回后再次检索的简要说明。

**文件说明**
- `demo.py`：统一演示入口（学习+办公），五轮对话、记忆检索与写回、冲突校验、完整 IO 与 JSON 展示（仅基于 `user_id` 隔离）。
- `memos_client.py`：MemOS 客户端，仅使用 `user_id` 分区；在请求前自动确保 `user_id`；内置请求重试、超时与可配置 SSL 验证（`MEMOS_VERIFY_SSL`）。
- `prompts.py`：统一场景系统提示 `SYSTEM_PROMPT_UNIFIED` 与 `build_unified_demo_prompt`。
- `llm_client.py`：统一模型客户端。
 - `langgraph_agent.py`：LangGraph 代理，支持交互式与非交互式两种模式（示例化问答）。
 - `main.py`：交互式演示入口，循环读取输入 → 回复 → 写回 MemOS，并可关键词检索摘要。
 - `api_server.py`：FastAPI 服务，提供健康检查与对话接口，便于压测与对接。

---

**压测 API 服务（FastAPI）**
- 启动服务：`uvicorn api_server:app --host 0.0.0.0 --port 8000`
- 主要端点：
  - `GET /health`：健康检查；返回 `{"status":"ok"}`。
  - `POST /chat`：对话接口；支持真实模型调用或本地模拟（`mock=true`）。
    - 入参（JSON）：
      - `messages`（可选）：如 `[{"role":"user","content":"你好"}]`
      - `prompt`（可选）：单条用户文本（若不传 `messages`）
      - `system`（可选）：系统提示，默认为简洁、结构化应答的助理
      - `mock`（可选）：布尔值，`true` 表示不调用模型，直接返回模拟回复（用于高并发压测）
    - 返回（JSON）：`model`、`content`、`usage`（可能为空）、`latency_ms`
- 示例：
  - 探活：`curl http://localhost:8000/health`
  - 模拟压测：`curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' -d '{"prompt":"安排下今天","mock":true}'`
  - 真实调用：`curl -X POST http://localhost:8000/chat -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"给我一个今天的简要计划"}]}'`

提示：进行压测时优先使用 `mock:true`，避免外部模型成为瓶颈；观察返回的 `latency_ms` 以做简单统计。
