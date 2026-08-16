"""配置的加载与保存（config.json）。"""
import json
import threading
from pathlib import Path

DEFAULT_CONFIG = {
    "bot": {
        # 后端: douyin（抖音网页版私信）
        "backend": "douyin",
        "poll_interval": 2.0,   # 消息轮询间隔（秒）
    },
    "douyin": {
        "profile_dir": ".douyin_profile",   # 浏览器登录态目录
    },
    "llm": {
        "base_url": "https://api.deepseek.com/v1",  # OpenAI 兼容接口地址
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.7,
        "max_tokens": 512,
        "timeout_seconds": 120,
    },
    "persona": (
        "你是一个在抖音上聊天的年轻网友，说话轻松随意、口语化，像朋友一样。"
        "回复一定要短，通常一两句话、一般不超过 40 字，不要长篇大论，不要用书面语和 AI 腔。"
        "可以自然地用一些网络流行语和梗（比如「家人们」「绝绝子」「泰裤辣」「6」「谁懂啊」这类），"
        "但不要硬凑、不要堆砌，偶尔带一个 emoji 就好，不要编造事实。"
        "如果对方发的是视频、图片或表情包（消息里会出现 [视频]、[图片]、[表情包] 这类标记），"
        "要顺着内容自然地接梗、吐槽或夸一句，回复同样要短、要好玩。"
    ),
    "auto_reply": {
        "enabled": False,              # 总开关（默认关闭，需手动开启）
        "only_at_me_in_groups": True,  # 群聊中仅在被 @ 时回复
        "min_interval_seconds": 10,    # 同一会话两次回复的最小间隔（秒）
        "max_context_turns": 20,       # 每个会话保留的上下文轮数
        "chats": {},                   # 会话名 -> {"enabled": true/false}
        "blacklist_keywords": ["刷单", "贷款"],
    },
}


class Config:
    """线程安全的配置读写。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self):
        data = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.path.exists():
            try:
                user = json.loads(self.path.read_text(encoding="utf-8"))
                self._merge(data, user)
            except Exception:
                pass  # 配置损坏时回退默认值
        return data

    @staticmethod
    def _merge(base, override):
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Config._merge(base[k], v)
            else:
                base[k] = v

    def get(self, dotted, default=None):
        with self._lock:
            node = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def set(self, dotted, value):
        with self._lock:
            parts = dotted.split(".")
            node = self.data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

    def save(self):
        with self._lock:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
