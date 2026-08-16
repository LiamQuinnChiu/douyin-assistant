"""回复决策、上下文记忆与提示词组装。"""
import collections
import random
import time


class Brain:
    def __init__(self, config, llm, log=None):
        self.config = config
        self.llm = llm
        self.log = log or (lambda *a, **k: None)
        self.memory = collections.defaultdict(lambda: collections.deque(maxlen=200))
        self._last_reply = {}

    def reset_memory(self, chat=None):
        if chat is None:
            self.memory.clear()
        else:
            self.memory.pop(chat, None)

    def should_reply(self, msg):
        cfg = self.config
        if not cfg.get("auto_reply.enabled"):
            return False, "自动回复未开启"
        if msg.is_self:
            return False, "跳过自己发送的消息"
        chat_cfg = cfg.get("auto_reply.chats", {}).get(msg.chat, {})
        if not chat_cfg.get("enabled"):
            return False, "该会话未勾选自动回复"
        if msg.is_group and cfg.get("auto_reply.only_at_me_in_groups") and not msg.is_at:
            return False, "群聊中未被 @，跳过"
        for kw in cfg.get("auto_reply.blacklist_keywords", []):
            if kw and kw in msg.content:
                return False, f"命中黑名单关键词: {kw}"
        interval = cfg.get("auto_reply.min_interval_seconds", 10)
        jitter = random.uniform(0, 8)  # 随机抖动，避免回复节奏太规律
        if time.time() - self._last_reply.get(msg.chat, 0) < interval + jitter:
            return False, "距上次回复太近，跳过"
        return True, ""

    def build_messages(self, msg):
        cfg = self.config
        messages = [{"role": "system", "content": cfg.get("persona") or ""}]
        hist = list(self.memory[msg.chat])
        max_turns = cfg.get("auto_reply.max_context_turns", 10)
        if max_turns > 0:
            hist = hist[-max_turns * 2:]
        messages.extend(hist)
        if msg.is_group:
            content = f"【群聊 {msg.chat}】{msg.sender} 说：{msg.content}"
        else:
            content = f"{msg.sender} 说：{msg.content}"
        messages.append({"role": "user", "content": content})
        return messages

    def handle(self, msg):
        """处理一条消息；返回要发送的回复文本，不回复时返回 None。"""
        ok, reason = self.should_reply(msg)
        if not ok:
            self.log(f"跳过 [{msg.chat}] {reason}")
            return None
        try:
            messages = self.build_messages(msg)
            self.log(f"正在为 [{msg.chat}] 生成回复 …", "info")
            reply = self.llm.chat(messages).strip()
        except Exception as e:
            self.log(f"模型调用失败: {e}", "error")
            return None
        if not reply:
            return None
        self.memory[msg.chat].append({"role": "user", "content": messages[-1]["content"]})
        self.memory[msg.chat].append({"role": "assistant", "content": reply})
        self._last_reply[msg.chat] = time.time()
        return reply
