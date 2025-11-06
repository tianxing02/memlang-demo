"""
llm_client.py

通俗说明：
- 统一管理大模型客户端与模型名读取，避免各处重复配置。
- 从 `.env` 读取 `OPENAI_API_KEY` 与可选的 `OPENAI_API_BASE`（自托管/代理场景）。
- 模型名默认使用 `gpt-4o-mini`，也可通过环境变量 `OPENAI_MODEL` 覆盖。
"""

from dotenv import load_dotenv
import os
import openai

load_dotenv()

def get_openai_client() -> openai.Client:
    """创建并返回 OpenAI 客户端。

    - 若配置了 `OPENAI_API_BASE`，则通过 `base_url` 指向自托管或代理服务。
    - 缺少 `OPENAI_API_KEY` 时抛出明确的错误提示，便于快速定位问题。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置，请在 .env 中配置后重试。")
    return openai.Client(api_key=api_key, base_url=api_base)


def get_openai_model(default: str = "gpt-4o-mini") -> str:
    """读取模型名，支持通过环境变量覆盖默认值。"""
    return os.getenv("OPENAI_MODEL", default)