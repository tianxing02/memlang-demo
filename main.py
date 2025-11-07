"""
main.py

通俗说明：
- 演示交互式代理的主入口：读取用户输入 → 生成回复 → 写回 MemOS → 可选查询摘要。
- 每次循环都将本轮的用户/助理消息写回到 MemOS，以保持记忆的连续性。
"""

import sys
from langgraph_agent import build_agent, build_agent_noninteractive
from memos_client import MemOSClient


def _summarize_memory(mem_result: dict) -> str:
    """将 MemOS 检索到的记忆上下文压缩为可读摘要，仅输出有用文字。"""
    if not mem_result or not isinstance(mem_result, dict):
        return "(无可用的记忆摘要)"

    container = mem_result
    for key in ("data", "result"):
        if isinstance(container.get(key), dict):
            container = container[key]
            break

    lines = []
    prefs = container.get("preference_detail_list", []) or container.get("preferences", []) or []
    facts = container.get("fact_detail_list", []) or container.get("facts", []) or []

    explicit = [p for p in prefs if p.get("preference_type") == "explicit_preference"]
    implicit = [p for p in prefs if p.get("preference_type") == "implicit_preference"]

    if explicit:
        lines.append("- 明确喜欢：")
        for p in explicit[:5]:
            pref = p.get("preference") or ""
            reason = (p.get("reasoning") or "")[:80]
            lines.append(f"  · {pref}" + (f"（理由：{reason}…）" if reason else ""))

    if implicit:
        lines.append("- 习惯倾向：")
        for p in implicit[:5]:
            pref = p.get("preference") or ""
            reason = (p.get("reasoning") or "")[:80]
            lines.append(f"  · {pref}" + (f"（依据：{reason}…）" if reason else ""))

    if facts:
        lines.append("- 近期事项/任务摘要：")
        for f in facts[:5]:
            title = f.get("title") or f.get("fact") or "事实"
            tr = f.get("time_range") or ""
            tags = f.get("tags") or []
            tag_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            if tr:
                lines.append(f"  · {title}（时间：{tr}；标签：{tag_str}）")
            else:
                lines.append(f"  · {title}（标签：{tag_str}）")

    note = container.get("preference_note")
    if note:
        lines.append("- 记忆注意事项：已省略详情，仅保留必要提示。")

    return "\n".join(lines) if lines else "(暂无偏好与事实摘要)"

def main():
    """交互式运行入口：初始化代理与 MemOS 客户端并进入循环（仅基于 user_id）。"""
    memos = MemOSClient()
    agent = build_agent()

    print("🧭 欢迎使用个人日程助手演示（MemOS + LangGraph）")

    while True:
        # 每次调用执行一次：ask_user -> generate_response（无需额外编排）
        state = agent.invoke({})
        query = state.get("query")
        response = state.get("response")

        # 保存记忆到 MemOS：记录用户输入与助理回复，形成跨会话的记忆链路
        if query and response:
            messages = [
                {"role": "user", "content": query},
                {"role": "assistant", "content": response}
            ]
            memos.add_conversation(messages)

        # 查询历史上下文：当用户输入包含 "摘要" 或 "summary" 时，示例性检索最近任务摘要
        if query and isinstance(query, str) and ("summary" in query.lower() or "摘要" in query):
            # 使用用户的 query 进行检索，仅基于 user_id
            res = memos.search_memory(query)
            print("🧠 记忆摘要：\n" + _summarize_memory(res))

if __name__ == "__main__":
    main()
