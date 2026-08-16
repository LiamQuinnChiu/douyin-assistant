"""聊天平台后端抽象接口。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class IncomingMessage:
    """一条收到的文本消息。"""
    chat: str               # 会话显示名（好友昵称或群标识）
    sender: str             # 发送者
    content: str            # 文本内容
    is_group: bool = False  # 是否群聊
    is_self: bool = False   # 是否自己发的
    is_at: bool = False     # 群聊中是否 @ 了机器人
    ts: float = 0.0         # 接收时间戳
    raw: object = field(default=None, repr=False)


class ChatAdapter(ABC):
    """聊天平台后端统一接口。"""

    name = "base"
    display_name = "Base"

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def get_chats(self) -> list: ...

    @abstractmethod
    def poll_messages(self) -> list: ...

    @abstractmethod
    def send_text(self, chat: str, text: str) -> None: ...

    def is_connected(self) -> bool:
        return False

    def set_listen_chats(self, chats) -> None:
        """可选：设置需要监听的会话。"""

    def resolve_target(self, chat: str) -> str:
        return chat
