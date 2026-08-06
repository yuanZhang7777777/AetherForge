"""模型客户端：DeepSeek 文本（json_object + thinking + max_tokens）与 APIMart 视觉/生图。

与现有 picturesGenerate 的关键差异（修复点）：
- response_format={"type":"json_object"} 保证合法 JSON
- 显式设置 max_tokens（防推理输出被截断）
- thinking 开启时用 reasoning_effort 控制深度，且不发 temperature（官方：thinking 下 temperature 无效）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from .config import settings


class ProviderError(RuntimeError):
    """可展示给前端的安全错误（不含密钥）。"""


def sanitize(text: str) -> str:
    return str(text).replace(settings.deepseek_api_key or "", "[redacted]").replace(
        settings.apimart_api_key or "", "[redacted]"
    )


def extract_json(text: str) -> Any:
    """鲁棒 JSON 提取：剥代码围栏，取首个平衡对象/数组。"""
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ProviderError("模型返回内容无法解析为 JSON")


class DeepSeekClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.timeout = settings.prompt_timeout_seconds

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        thinking: bool = True,
    ) -> dict[str, Any]:
        if not settings.deepseek_enabled:
            raise ProviderError("DeepSeek 文本模型已关闭")
        if not self.api_key:
            raise ProviderError("缺少 DEEPSEEK_API_KEY")
        payload: dict[str, Any] = {
            "model": model or settings.deepseek_prompt_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens or settings.max_tokens_deep,
        }
        if thinking:
            # 官方：thinking 默认开启；开启时 temperature 无效，用 reasoning_effort 控深度
            payload["reasoning_effort"] = reasoning_effort or settings.reasoning_effort_deep
            payload["thinking"] = {"type": "enabled"}
        elif temperature is not None:
            payload["temperature"] = temperature

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                continue
            body = resp.json()
            if resp.status_code >= 400:
                raise ProviderError(sanitize(f"DeepSeek 返回 {resp.status_code}: {body}"))
            content = self._output_text(body)
            if not content and attempt == 0:
                last_error = ProviderError("DeepSeek 返回空内容，重试一次")
                continue
            if not content:
                raise ProviderError("DeepSeek 返回空内容")
            try:
                return {"json": extract_json(content), "raw_text": content}
            except ProviderError:
                if attempt == 0:
                    last_error = ProviderError("DeepSeek JSON 解析失败，重试一次")
                    continue
                raise
        raise ProviderError(sanitize(f"模型服务不可用：{last_error}"))

    @staticmethod
    def _output_text(body: dict) -> str:
        choices = body.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            content = "\n".join(parts)
        return str(content).strip()


class APIMartClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.apimart_api_key
        self.base_url = (base_url or settings.apimart_base_url).rstrip("/")
        self.timeout = settings.prompt_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        base = self.base_url
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}{path}"

    def upload_image(self, path: str | Path) -> str:
        """把本地图片上传为可被视觉/生图模型引用的 URL。"""
        if not self.api_key:
            raise ProviderError("缺少 APIMART_API_KEY")
        with Path(path).open("rb") as handle:
            resp = requests.post(
                self._url("/v1/uploads/images"),
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"file": handle},
                timeout=self.timeout,
            )
        body = resp.json()
        if resp.status_code >= 400:
            raise ProviderError(sanitize(f"图片上传失败 {resp.status_code}: {body}"))
        url = body.get("url")
        if not isinstance(url, str) or not url:
            raise ProviderError("图片上传未返回 url")
        return url

    def to_image_url(self, source: str | Path) -> str:
        """本地路径先上传；已是 http(s) URL 直接使用。"""
        s = str(source)
        if s.startswith("http://") or s.startswith("https://"):
            return s
        return self.upload_image(s)

    def observe_image(self, instruction: str, image_sources: list[str | Path]) -> str:
        """视觉理解（逐图证据提取），返回文本。"""
        if not self.api_key:
            raise ProviderError("缺少 APIMART_API_KEY")
        urls = [self.to_image_url(src) for src in image_sources]
        content: list[dict[str, Any]] = [{"type": "input_text", "text": instruction}]
        content.extend({"type": "input_image", "image_url": url} for url in urls)
        resp = requests.post(
            self._url("/v1/responses"),
            json={"model": settings.apimart_vision_model, "input": [{"role": "user", "content": content}]},
            headers=self._headers(),
            timeout=self.timeout,
        )
        body = resp.json()
        if resp.status_code >= 400:
            raise ProviderError(sanitize(f"视觉识别失败 {resp.status_code}: {body}"))
        return self._responses_output_text(body)

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        image_sources: list[str | Path] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        thinking: bool = True,
    ) -> dict[str, Any]:
        """APIMart Responses JSON 调用；参数签名兼容 DeepSeekClient。"""
        if not self.api_key:
            raise ProviderError("缺少 APIMART_API_KEY")
        urls = [self.to_image_url(src) for src in image_sources or []]
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": f"SYSTEM:\n{system}\n\nUSER:\n{user}"}
        ]
        content.extend({"type": "input_image", "image_url": url} for url in urls)
        payload: dict[str, Any] = {
            "model": model or settings.apimart_prompt_model,
            "input": [{"role": "user", "content": content}],
        }
        if max_tokens:
            payload["max_output_tokens"] = max_tokens
        resp = requests.post(
            self._url("/v1/responses"),
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        body = resp.json()
        if resp.status_code >= 400:
            raise ProviderError(sanitize(f"APIMart 文本模型返回 {resp.status_code}: {body}"))
        text = self._responses_output_text(body)
        if not text:
            raise ProviderError("APIMart 文本模型返回空内容")
        return {"json": extract_json(text), "raw_text": text}

    def submit_generation(self, prompt: str, image_urls: list[str], size: str, resolution: str) -> str:
        """提交生图任务，返回 task_id。参考图通过 image_urls 传入（gpt-image-2）。"""
        if not self.api_key:
            raise ProviderError("缺少 APIMART_API_KEY")
        payload = {
            "model": settings.apimart_image_model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "resolution": resolution,
            "official_fallback": False,
        }
        if image_urls:
            payload["image_urls"] = list(image_urls)
        resp = requests.post(self._url("/v1/images/generations"), json=payload, headers=self._headers(), timeout=self.timeout)
        body = resp.json()
        if resp.status_code >= 400:
            raise ProviderError(sanitize(f"生图提交失败 {resp.status_code}: {body}"))
        data = body.get("data")
        first = data[0] if isinstance(data, list) and data else data
        task_id = (
            first.get("task_id") or first.get("id") if isinstance(first, dict) else body.get("task_id") or body.get("id")
        )
        if not task_id:
            raise ProviderError("生图响应未包含 task_id")
        return str(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        resp = requests.get(
            self._url(f"/v1/tasks/{task_id}"),
            headers=self._headers(),
            params={"language": "zh"},
            timeout=self.timeout,
        )
        body = resp.json()
        if resp.status_code >= 400:
            raise ProviderError(sanitize(f"查询生图任务失败 {resp.status_code}: {body}"))
        return body.get("data", body)

    def download(self, url: str) -> bytes:
        resp = requests.get(url, timeout=self.timeout)
        if resp.status_code >= 400:
            raise ProviderError(f"下载图片失败 {resp.status_code}")
        return resp.content

    @staticmethod
    def _responses_output_text(body: dict) -> str:
        output = body.get("output") or []
        parts: list[str] = []
        for item in output:
            if isinstance(item, dict):
                if item.get("type") == "message" and isinstance(item.get("content"), list):
                    for part in item["content"]:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            parts.append(part["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "\n".join(parts)
