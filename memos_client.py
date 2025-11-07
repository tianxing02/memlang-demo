"""
memos_client.py

通俗说明：
- 与 MemOS 服务交互的轻量客户端，仅基于 `user_id` 进行记忆分区。
- 所有必要的连接配置从 `.env` 中读取，包括：`MEMOS_API_KEY`、`MEMOS_BASE_URL`（可选 `OPENAI_API_BASE`）。
- `user_id` 可由调用方显式传入；若未传入且环境变量也未设置，将自动随机生成一个。
- 主要方法：`add_conversation(messages)` 写入消息，`search_memory(query)` 检索记忆。
"""

import os
import json
import requests
import uuid
from dotenv import load_dotenv

load_dotenv()

class MemOSClient:
    """MemOS 客户端封装：读取配置并暴露写入/检索接口（基于 user_id）。

    支持在初始化时传入 `user_id`；若未传入则优先使用环境变量 `USER_ID`，如仍为空则随机生成。
    """

    def __init__(self, user_id: str | None = None):
        # 从环境变量读取连接信息；user_id 可外部传入，或使用环境变量/随机生成
        self.api_key = os.getenv("MEMOS_API_KEY")
        self.base_url = os.getenv("MEMOS_BASE_URL")
        self.user_id = user_id or os.getenv("USER_ID") or f"user_{uuid.uuid4().hex[:10]}"

        # 网络/SSL配置（可通过环境变量控制）
        verify_ssl_env = (os.getenv("MEMOS_VERIFY_SSL", "true") or "true").strip().lower()
        self.verify_ssl = verify_ssl_env in ("1", "true", "yes", "on")
        timeout_env = (os.getenv("MEMOS_TIMEOUT", "20") or "20").strip()
        try:
            self.timeout = float(timeout_env)
        except ValueError:
            self.timeout = 20.0

        # 规范化 base_url（确保协议与去除尾部斜杠）
        if self.base_url:
            if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
                self.base_url = "https://" + self.base_url
            self.base_url = self.base_url.rstrip("/")

        # 构建带重试的 Session
        from urllib3.util.retry import Retry
        from requests.adapters import HTTPAdapter
        self._session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _ensure_user_id(self):
        """在请求前确保存在 user_id；若缺失则随机生成一个。"""
        if not getattr(self, "user_id", None):
            self.user_id = f"user_{uuid.uuid4().hex[:10]}"

    def _url(self, path: str) -> str:
        path = path.strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            # 某些服务端连接复用在特定网络下易引发 EOF，显式关闭连接可提升稳定性
            "Connection": "close",
        }
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        return headers

    def add_conversation(self, messages: list):
        """将对话内容存入 MemOS 记忆（仅按 user_id 分区）。

        参数：
        - messages: 列表形式的消息体，如 [{"role": "user", "content": "..."}]

        返回：
        - 服务端返回的 JSON 对象（dict），包含写入结果。
        """
        # 在请求前确保 user_id 存在
        self._ensure_user_id()
        url = self._url("/add/message")
        headers = self._headers()
        data = {
            "user_id": self.user_id,
            "messages": messages,
            "conversation_id": f"session_{uuid.uuid4().hex[:10]}"
        }
        try:
            res = self._session.post(url, headers=headers, json=data, timeout=self.timeout, verify=self.verify_ssl)
        except Exception as e:
            raise Exception(f"写入对话请求失败：{e}")
        if res.status_code != 200:
            raise Exception(f"写入对话失败：{res.status_code} {res.text}")
        return res.json()

    def search_memory(self, query: str):
        """查询记忆摘要或执行检索任务（仅按 user_id 分区）。

        参数：
        - query: 查询指令（自然语言或固定模板），由服务端解析执行。

        返回：
        - 服务端返回的 JSON 对象（dict），一般包含记忆详情列表与偏好列表等。
        """
        # 在请求前确保 user_id 存在
        self._ensure_user_id()
        url = self._url("/search/memory")
        headers = self._headers()
        data = {
            "query": query,
            "user_id": self.user_id,
            "conversation_id": f"session_{uuid.uuid4().hex[:10]}"
        }
        try:
            res = self._session.post(url, headers=headers, json=data, timeout=self.timeout, verify=self.verify_ssl)
        except Exception as e:
            raise Exception(f"检索记忆请求失败：{e}")
        if res.status_code != 200:
            raise Exception(f"检索记忆失败：{res.status_code} {res.text}")
        return res.json()
