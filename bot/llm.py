"""OpenAI 兼容接口的 LLM 客户端（默认 DeepSeek）。"""
import requests


class LLMError(Exception):
    """模型调用失败。"""


class LLMClient:
    def __init__(self, config):
        self.config = config

    def chat(self, messages):
        """发送消息列表，返回模型文本回复。"""
        cfg = self.config
        api_key = (cfg.get("llm.api_key") or "").strip()
        if not api_key:
            raise LLMError("API Key 为空，请在 GUI「模型设置」中填写")
        base = (cfg.get("llm.base_url") or "").rstrip("/")
        if not base:
            raise LLMError("接口地址为空")
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg.get("llm.model") or "deepseek-chat",
            "messages": messages,
            "temperature": float(cfg.get("llm.temperature") or 0.7),
            "max_tokens": int(cfg.get("llm.max_tokens") or 2048),
            "stream": False,
        }
        try:
            resp = requests.post(
                url, headers=headers, json=payload,
                timeout=float(cfg.get("llm.timeout_seconds") or 120),
            )
        except requests.RequestException as e:
            raise LLMError(f"网络错误: {e}") from e
        if resp.status_code != 200:
            raise LLMError(f"API 返回 {resp.status_code}: {resp.text[:300]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMError(f"响应解析失败: {e}") from e
        if not content:
            raise LLMError("模型返回了空内容")
        return str(content).strip()
