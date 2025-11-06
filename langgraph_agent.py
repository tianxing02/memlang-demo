"""
langgraph_agent.py

通俗说明：
- 使用 LangGraph 构建一个最小化的“问答代理”，支持交互与非交互两种模式。
- 交互模式：读取用户输入 → 调用大模型生成回复 → 打印并返回状态。
- 非交互模式：读取 state['query'] → 调用大模型生成回复（包含认证错误兜底）。
"""

from dotenv import load_dotenv
import os
import json
from typing import TypedDict
from langgraph.graph import StateGraph
import openai

# 定义状态模式（LangGraph 新版需要显式 state_schema）
class AgentState(TypedDict, total=False):
    """代理的最小状态定义：保存用户输入与模型回复。"""
    query: str
    response: str

load_dotenv()  # 加载 .env 文件

# 读取并校验 OPENAI_API_KEY
_api_key = os.getenv("OPENAI_API_KEY")
_api_base = os.getenv("OPENAI_API_BASE") 
_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 与参考实现一致：使用 openai.Client，并支持 base_url
client = openai.Client(api_key=_api_key, base_url=_api_base)

def build_agent():
    """创建交互式 LangGraph 流程：循环读取输入并生成回复。"""
    graph = StateGraph(AgentState)

    def ask_user(state):
        """读取用户输入，写入到状态的 query 字段。"""
        user_query = input("👤 You: ")
        state["query"] = user_query
        return state

    def generate_response(state):
        """调用大模型生成回复，保存到状态并打印。"""
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": "你是一名可靠的日程与任务助理，回答应简洁、结构化并可执行。"},
                {"role": "user", "content": state.get("query", "")}
            ]
        )
        state["response"] = response.choices[0].message.content
        print("🤖 Assistant:", state["response"])
        return state

    graph.add_node("ask_user", ask_user)
    graph.add_node("generate_response", generate_response)
    graph.add_edge("ask_user", "generate_response")

    graph.set_entry_point("ask_user")
    return graph.compile()


def build_agent_noninteractive():
    """创建非交互 LangGraph 流程：从 state['query'] 直接生成回复。"""
    graph = StateGraph(AgentState)

    def generate_response(state):
        """调用大模型生成回复；认证失败时给出中文错误提示。"""
        try:
            response = client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": "你是一名可靠的日程与任务助理，回答应简洁、结构化并可执行。"},
                    {"role": "user", "content": state.get("query", "")}
                ]
            )
            state["response"] = response.choices[0].message.content
        except openai.AuthenticationError:
            state["response"] = (
                "OpenAI API 认证失败：请检查 OPENAI_API_KEY 是否有效。"
                "如使用自托管/代理服务，请确认 OPENAI_API_BASE 和模型配置。"
            )
        print("🤖 Assistant:", state.get("response", ""))
        return state

    graph.add_node("generate_response", generate_response)
    graph.set_entry_point("generate_response")
    return graph.compile()
