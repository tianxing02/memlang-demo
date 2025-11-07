"""
api_server.py

简述：
- 提供压测用的简单 API 服务，包含一个 `POST /chat` 对话接口。
- 依赖 `FastAPI` 与项目内的 `llm_client.py`，可选择模拟回复以避免外部调用。

运行：
- uvicorn api_server:app --host 0.0.0.0 --port 8000
"""

import time
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from llm_client import get_openai_client, get_openai_model


app = FastAPI(title="MemLang Demo API", version="0.1.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: Optional[List[ChatMessage]] = None
    prompt: Optional[str] = None
    system: Optional[str] = "你是一名可靠的日程与任务助理，回答应简洁、结构化并可执行。"
    mock: bool = False


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    start = time.time()

    # 构造消息列表
    messages: List[Dict[str, str]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})

    if req.messages and len(req.messages) > 0:
        for m in req.messages:
            messages.append({"role": m.role, "content": m.content})
    elif req.prompt:
        messages.append({"role": "user", "content": req.prompt})
    else:
        raise HTTPException(status_code=400, detail="缺少 messages 或 prompt")

    # 可选：模拟回复，便于本地压测不依赖外部服务
    if req.mock:
        latency_ms = int((time.time() - start) * 1000)
        # 简单模拟：返回最后一条用户内容的缩略回复
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return {
            "model": "mock",
            "content": f"收到：{last_user[:64]}...",
            "usage": None,
            "latency_ms": latency_ms,
        }

    try:
        client = get_openai_client()
        model = get_openai_model()
        resp = client.chat.completions.create(model=model, messages=messages)
        content = resp.choices[0].message.content
        usage = getattr(resp, "usage", None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型调用失败：{e}")

    latency_ms = int((time.time() - start) * 1000)
    return {
        "model": model,
        "content": content,
        "usage": usage.dict() if hasattr(usage, "dict") else usage,
        "latency_ms": latency_ms,
    }