# 手把手构建「有记忆的个人日程助手」——从零到跑通（超详细）

本教程面向“完全小白”的开发者，带你从零开始跑通一个“有记忆”的个人日程助手：安装环境 → 配好密钥 → 跑统一演示 → 看懂代码如何把“检索历史记忆、构建提示词、生成计划、校验冲突、写回记忆”串成闭环。每一步都尽量简单、通俗，并在关键处结合项目代码说明。

你将收获
- 跑通最小可用版本：一个能记住你的偏好与历史任务的助手。
- 掌握关键文件：`demo.py`（统一演示）、`memos_client.py`（记忆交互）、`main.py`（交互入口）、`prompts.py`（提示词）。
- 学会扩展：如何加入提醒/摘要/改期等分支能力，如何排查网络与 SSL 问题。

---

## 1. 环境准备（3 步）

- 安装依赖：`pip install -r requirements.txt`
- 新建/编辑 `.env`（放在项目根目录），至少填好：
  - `OPENAI_API_KEY=你的OpenAI密钥`
  - `MEMOS_API_KEY=你的MemOS密钥`
  - `MEMOS_BASE_URL=https://memos.memtensor.cn/api/openmem/v1`
- 可选配置（先不用也能跑）：
  - `OPENAI_API_BASE`、`OPENAI_MODEL`（如企业代理或自定义模型）
  - `MEMOS_VERIFY_SSL=true`（公司代理下如报 SSL 错，可改为 `false` 临时绕过）
  - `MEMOS_TIMEOUT=20`（网络慢时可加大）

小提示：客户端在每次请求前会确保存在 `user_id`，若你不给，它会随机生成一个（并打印）。整个记忆隔离只基于 `user_id`。

---

## 2. 跑统一演示（1 条命令）

- 执行：`python3 demo.py`
- 正常输出会包含：
  - `📚 参考记忆条目`：把检索到的历史记忆与偏好逐行打印（更易读）。
  - `🗣️ 用户指令` 与 `🤖 系统输出`：本轮输入与模型的回复。
  - `🔧 计划更新 JSON`：用 `BEGIN_PLAN_UPDATE ... END_PLAN_UPDATE` 包裹，便于提取与写回。
  - `🧪 校验`：简单的时间冲突检查与说明。

如果你第一次就看到“计划更新 JSON”和“冲突校验”，说明闭环已跑起来：检索 → 生成 → 校验 → 写回。

---

## 3. 看懂业务与记忆（先理解再改代码）

- 场景：学习与办公混合。每天学习约 2 小时，穿插固定会议/家庭活动/培训等；助手要兼顾偏好与约束，跨日承接。
- 记忆类型：
  - 显式偏好（你直接说的）：如“周六上午学习效率更高”。
  - 隐式偏好（从行为推断）：如“晚上尽量不安排高强度任务”。
  - 承诺（固定时段）：如“09:30–10:00 晨会”。
  - 约束（必须在某段时间完成）：如“本周内完成合规培训”。

---

## 4. 代码走读（入口 → 检索 → 提示词 → 输出 → 写回）

**demo.py：统一演示入口**
- 思路是“每次执行前先检索历史记忆”，再把参考记忆放入提示词，生成结构化计划更新，然后做冲突校验并写回。核心流程如下（简化版，与项目一致）：

```python
# 1) 检索：用本轮的用户指令做查询
mem_obj_round_q = memos.search_memory(extra_instruction)

# 2) 格式化：把记忆列表逐行输出，更便于阅读与提示词使用
mem_ctx = _format_mem_ctx_lines(mem_obj_round_q)

# 3) 构造提示词：目标 + 参考记忆
user_prompt = build_unified_demo_prompt(goal_text, mem_ctx)

# 4) 调用模型：传入系统提示、历史消息、用户提示、用户指令
messages = [
    {"role": "system", "content": SYSTEM_PROMPT_UNIFIED},
    *history_messages,
    {"role": "user", "content": user_prompt},
    {"role": "user", "content": extra_instruction},
]
response = client.chat.completions.create(model=model, messages=messages)
content = response.choices[0].message.content

# 5) 解析结构化计划更新（如果模型产出）
plan_json = _parse_plan_update_json_from_content(content)

# 6) 写回：把用户/助手消息与计划更新摘要写入记忆
write_messages = [
    {"role": "user", "content": user_prompt},
    {"role": "user", "content": extra_instruction},
    {"role": "assistant", "content": content},
]
if plan_json is not None:
    write_messages.append({"role": "assistant", "content": json.dumps({"PlanUpdate": plan_json}, ensure_ascii=False)})
memos.add_conversation(write_messages)
```

- 逐行格式化记忆的函数（项目内一致）：

```python
def _format_mem_ctx_lines(mem_result: dict) -> str:
    container = mem_result if isinstance(mem_result, dict) else {}
    data = container.get("data") if isinstance(container.get("data"), dict) else container
    lines = []

    def emit_list(name: str):
        items = data.get(name)
        if isinstance(items, list):
            lines.append(f"{name}:")
            for it in items:
                if isinstance(it, (dict, list)):
                    lines.append(json.dumps(it, ensure_ascii=False))
                else:
                    lines.append(str(it))
            lines.append("")

    emit_list("memory_detail_list")
    emit_list("preference_detail_list")
    return "\n".join(lines).strip()
```

**memos_client.py：记忆服务客户端**
- 负责与 MemOS 通信。统一用 `user_id` 做隔离，已经去掉 `conversation_id`。
- 已内置网络稳健性：
  - `requests.Session` + 重试（对 429/5xx）
  - 显式 `Connection: close` 降低长连接导致的 EOF 风险
  - 可配置 `MEMOS_VERIFY_SSL` 与 `MEMOS_TIMEOUT`
- 典型调用：

```python
# 写回对话，让服务端生成/更新记忆
memos.add_conversation([
    {"role": "user", "content": user_prompt},
    {"role": "user", "content": extra_instruction},
    {"role": "assistant", "content": content},
])

# 用用户的真实 Query 做检索
mem_obj_round_q = memos.search_memory(extra_instruction)
```

**main.py：交互式入口**
- 循环读取用户输入 → 回复 → 写回 → 可选检索摘要（当输入包含 `summary`）。

**prompts.py：提示词构建**
- `SYSTEM_PROMPT_UNIFIED` 定义了统一场景的系统提示词；`build_unified_demo_prompt` 把目标与参考记忆拼成简洁的用户提示词。

---

## 5. 从最小到可进化（你可以这样扩展）

- 把流程画成图：意图识别 → 记忆检索 → 执行（生成计划/改期） → 写回 → 响应。
- 冲突检测：解析计划中的时段，与承诺/已排事项做重叠检查，给出改期建议。
- 承接策略：未完成的事项做 rollover（承接到下一天/时段），同时写回偏好更新。
- 摘要与解释：为最终响应加入“引用来源与裁决规则”，提升可解释性和可信度。

---

## 6. 故障排除（网络与 SSL 常见坑）

- `SSLError: UNEXPECTED_EOF_WHILE_READING`：
  - 确认 `MEMOS_BASE_URL` 正确（含协议与完整路径）。
  - 公司代理拦截 TLS：临时 `MEMOS_VERIFY_SSL=false`（仅在可信网络使用）。
  - 调整 `MEMOS_TIMEOUT` 或升级依赖：`pip install -U requests urllib3 certifi`。
  - 我们已做连接关闭与重试，仍异常可重试运行或检查代理配置。

---

## 7. 练手任务（马上试一试）

- 在 `seed_unified_scenario` 增加“周六上午高效学习”的显式偏好，`python3 demo.py` 观察是否被引用。
- 在某一轮加入“客户汇报改期到周四 14:00-16:00”的指令，观察冲突检测与裁决输出。
- 在 `main.py` 输入包含 `summary` 的查询（如 “summary my recent tasks”），查看记忆摘要输出。

---

## 8. 最小 50 行示例（可复制试跑）

下面是一个把“检索 → 提示词 → 生成 → 写回”串起来的最小示例，帮助你理解最核心链路（伪代码，贴近项目结构）：

```python
import json
from memos_client import MemOSClient
from llm_client import client
from prompts import SYSTEM_PROMPT_UNIFIED, build_unified_demo_prompt

# 引用项目里的同名函数即可
from demo import _format_mem_ctx_lines, _parse_plan_update_json_from_content

def minimal_round(goal_text: str, instruction: str):
    memos = MemOSClient()
    # 1) 检索
    mem_obj = memos.search_memory(instruction)
    mem_ctx = _format_mem_ctx_lines(mem_obj)
    # 2) 提示词
    user_prompt = build_unified_demo_prompt(goal_text, mem_ctx)
    # 3) 调用模型
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT_UNIFIED},
        {"role": "user", "content": user_prompt},
        {"role": "user", "content": instruction},
    ]
    content = client.chat.completions.create(model="gpt-4o-mini", messages=msgs).choices[0].message.content
    # 4) 写回
    write_messages = [
        {"role": "user", "content": user_prompt},
        {"role": "user", "content": instruction},
        {"role": "assistant", "content": content},
    ]
    # 可选：解析并写回计划更新
    plan_json = _parse_plan_update_json_from_content(content)
    if plan_json:
        write_messages.append({"role": "assistant", "content": json.dumps({"PlanUpdate": plan_json}, ensure_ascii=False)})
    memos.add_conversation(write_messages)
    return content

if __name__ == "__main__":
    goal = "每天学习 2 小时并兼顾固定会议与家庭活动"
    print(minimal_round(goal, "这周政治学学习安排，避开周五下午"))
```

这段示例是把项目里的关键调用链“压缩”成最短、最清晰的版本，方便你快速理解和复用。

---

祝你构建顺利！需要我再加一段“运行输出示例”，帮助你对齐正常与异常状态下应该看到的内容吗？也欢迎你把这个教程发给团队新同学，作为入门资料。