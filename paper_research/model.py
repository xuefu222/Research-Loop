"""Qwen 的有限预算 HTTP 客户端；不记录密钥、请求头和完整提示词。"""
import json
import time
import threading
from datetime import datetime, timezone
import httpx
from .config import model_config, ROOT

_AUDIT_LOCK = threading.Lock()


class ModelClient:
    def __init__(self, config=None, max_calls=8):
        self.config = config or model_config()
        self.max_calls = max_calls
        self.calls = []
        if not all(self.config.get(key) for key in ("base_url", "model", "api_key")):
            raise RuntimeError("请在 config/model.local.json 或 MAIN_* 环境变量配置模型接口")

    def text(self, messages, role="main", json_mode=True, _retried=False):
        if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
            raise ValueError("messages 必须为消息对象列表")
        if len(self.calls) >= self.max_calls:
            raise RuntimeError("已达到本次任务的模型调用预算")
        event = {"role": role, "model": self.config["model"], "status": "started",
                 "started_at_utc": datetime.now(timezone.utc).isoformat()}
        self.calls.append(event)
        start = time.monotonic()
        try:
            payload = {"model": self.config["model"], "messages": messages,
                "temperature": 0, "max_tokens": int(self.config.get("max_output_tokens", 2400))}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            with httpx.Client(timeout=float(self.config.get("timeout", 60))) as client:
                response = client.post(self.config["base_url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.config["api_key"]}, json=payload)
            event["http_status"] = response.status_code
            if response.status_code >= 400:
                event["status"] = "failed"
                raise RuntimeError(f"模型接口返回 HTTP {response.status_code}，请检查接口配置和额度")
            value = response.json()
            event["resolved_model"] = value.get("model")
            event["usage"] = value.get("usage", {})
            event["status"] = "completed"
            return value["choices"][0]["message"]["content"]
        except httpx.HTTPError as error:
            event["status"] = "failed"
            if not _retried and len(self.calls) < self.max_calls:
                time.sleep(0.5)
                return self.text(messages, role, json_mode, _retried=True)
            raise RuntimeError("模型网络调用失败：" + type(error).__name__) from None
        finally:
            event["elapsed_seconds"] = round(time.monotonic() - start, 3)
            with _AUDIT_LOCK:
                path = ROOT / "output/model_calls.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def json(self, system, data, role="main"):
        text = self.text([{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)}], role)
        return json.loads(text)
