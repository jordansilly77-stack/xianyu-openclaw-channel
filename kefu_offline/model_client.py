"""OpenAI 兼容聊天接口。密钥只从环境读取，不写进仓库或日志。"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Optional


class ModelCallError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        super().__init__(kind if not detail else f"{kind}: {detail}")


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = api_key or ""
        self.model = (model or "").strip()
        self.timeout = timeout
        if not self.base_url or not self.api_key or not self.model:
            raise ModelCallError("config", "缺少 base_url、api_key 或 model")

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        timeout_raw = os.environ.get("OPENAI_TIMEOUT", "30")
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 30.0
        return cls(
            base_url=os.environ.get("OPENAI_BASE_URL", ""),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", ""),
            timeout=timeout,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = getattr(response, "status", 200)
        except socket.timeout as exc:
            raise ModelCallError("timeout", self._scrub(str(exc))) from None
        except TimeoutError as exc:
            raise ModelCallError("timeout", self._scrub(str(exc))) from None
        except urllib.error.HTTPError as exc:
            raise ModelCallError("http", self._scrub(f"status={exc.code}")) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            kind = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) else "connection"
            raise ModelCallError(kind, self._scrub(str(reason))) from None
        if status != 200:
            raise ModelCallError("http", f"status={status}")
        try:
            body: Any = json.loads(raw)
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ModelCallError("bad_response", "响应里没有 choices[0].message.content") from None
        if not isinstance(content, str) or not content.strip():
            raise ModelCallError("bad_response", "回复为空")
        return content.strip()

    def _scrub(self, text: str) -> str:
        if self.api_key:
            text = text.replace(self.api_key, "***")
        return text[:300]


def missing_model_env() -> list[str]:
    return [
        name
        for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")
        if not (os.environ.get(name) or "").strip()
    ]


def model_enabled() -> bool:
    return os.environ.get("KEFU_MODEL_MODE", "rules").strip().lower() == "openai"
