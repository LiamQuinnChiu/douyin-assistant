"""基于 Playwright 的抖音网页版私信适配器。

原理: 用 Playwright 控制系统 Edge/Chrome 打开抖音网页版私信页
(https://www.douyin.com/chat?isPopup=1)，通过 DOM 读取消息、操作 Slate 编辑器发送回复。

选择器基于真实页面 DOM（语义化类名）:
- 会话列表项: [class*='conversationConversationItemwrapper']
- 会话标题:   [class*='conversationConversationItemtitle']
- 消息文本:   [class*='TextMessageText']（自己的消息祖先含 isFromMe）
- 输入框:     [data-slate-editor='true']（Slate 编辑器，contenteditable）
- 发送按钮:   .e2e-send-msg-btn

登录: 浏览器可见，首次扫码登录，登录态持久化到 .douyin_profile。
"""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .base import ChatAdapter, IncomingMessage

DOUYIN_URL = "https://www.douyin.com"
MESSAGES_URL = "https://www.douyin.com/chat?isPopup=1"

STEALTH_SCRIPT = """Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });"""

# 提取消息：文本 + 视频/图片/表情等非文本类型，并标注是否自己发送
EXTRACT_MESSAGES_JS = """() => {
    const out = [];
    const seen = new Set();
    const PLACE = { video: '[视频]', image: '[图片]', emoji: '[表情包]', voice: '[语音]' };
    const push = (kind, text, self) => {
        const key = (self ? 's' : 'o') + '|' + kind + '|' + text;
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ kind: kind, text: text || PLACE[kind] || '', self: self });
    };
    // 文本消息
    document.querySelectorAll('[class*="TextMessageText"]').forEach(t => {
        const text = (t.textContent || '').trim();
        if (!text || text.length > 500) return;
        let p = t, self = false;
        for (let i = 0; i < 8 && p; i++) {
            if (/isFromMe/.test(p.className || '')) { self = true; break; }
            p = p.parentElement;
        }
        push('text', text, self);
    });
    // 非文本消息：视频（video 标签）、图片、表情
    const list = document.querySelector('[class*="messageMessageList"]');
    const scope = list || document;
    scope.querySelectorAll('video, [class*="VideoMessage"], [class*="ImageMessage"], [class*="EmotionMessage"], [class*="VoiceMessage"]').forEach(m => {
        let p = m, self = false;
        for (let i = 0; i < 8 && p; i++) {
            if (/isFromMe/.test(p.className || '')) { self = true; break; }
            p = p.parentElement;
        }
        const cls = (m.className || '') + ' ' + (m.tagName || '');
        let kind = 'video';
        if (/image|picture/i.test(cls)) kind = 'image';
        else if (/emotion|emoji|sticker/i.test(cls)) kind = 'emoji';
        else if (/voice|audio/i.test(cls)) kind = 'voice';
        push(kind, '', self);
    });
    return out;
}"""


class DouyinAdapter(ChatAdapter):
    name = "douyin"
    display_name = "抖音网页版私信（Playwright）"

    def __init__(self, log=None, profile_dir=None):
        self.log = log or (lambda *a, **k: None)
        self._profile_dir = str(profile_dir or (Path.cwd() / ".douyin_profile"))
        self._pw = None
        self._context = None
        self._page = None
        self._executor = None
        self._seen = {}
        self._sent = set()
        self._connected = False

    # ------------------------------------------------------ 对外接口
    def connect(self):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="douyin")
        logged_in = self._executor.submit(self._connect_impl).result(timeout=180)
        self._connected = True
        return logged_in

    def disconnect(self):
        if self._executor is None:
            return
        try:
            self._executor.submit(self._close_impl).result(timeout=30)
        except Exception:
            pass
        self._executor.shutdown(wait=False)
        self._executor = None
        self._connected = False

    def is_connected(self):
        return self._connected

    def get_chats(self):
        if self._executor is None:
            return []
        try:
            return self._executor.submit(self._get_chats_impl).result(timeout=40)
        except Exception:
            return []

    def poll_messages(self):
        if self._executor is None:
            return []
        try:
            return self._executor.submit(self._poll_impl).result(timeout=45)
        except Exception as e:
            self.log(f"轮询异常: {e}", "error")
            return []

    def send_text(self, chat, text):
        if self._executor is None:
            raise RuntimeError("未连接")
        self._sent.add(text)
        return self._executor.submit(self._send_impl, chat, text).result(timeout=45)

    def get_recent_messages(self, limit=10):
        """返回当前会话最近的消息列表 [(is_self, text), ...]，用于手动生成回复。"""
        if self._executor is None:
            return []
        try:
            return self._executor.submit(self._recent_messages_impl, limit).result(timeout=40)
        except Exception:
            return []

    # ------------------------------------------------------ 实现
    def _connect_impl(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        ctx = None
        for channel in ("msedge", "chrome"):
            try:
                ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=self._profile_dir,
                    channel=channel,
                    headless=False,
                    args=args,
                    viewport={"width": 1280, "height": 820},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                self.log(f"已通过 {channel} 启动浏览器", "info")
                break
            except Exception as e:
                self.log(f"{channel} 启动失败: {e}", "error")
        if ctx is None:
            ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=self._profile_dir,
                headless=False,
                args=args,
                viewport={"width": 1280, "height": 820},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            self.log("已用 Playwright 自带 Chromium 启动", "info")
        self._context = ctx
        self._context.add_init_script(STEALTH_SCRIPT)
        self._page = self._context.new_page()
        self._page.set_default_timeout(15000)
        try:
            self._page.goto(MESSAGES_URL, wait_until="domcontentloaded")
        except Exception:
            self._page.goto(DOUYIN_URL, wait_until="domcontentloaded")
        time.sleep(5)
        try:
            self._page.bring_to_front()
        except Exception:
            pass
        logged_in = self._check_login_impl()
        self.log(
            "已打开抖音私信页(" + self._page.url + ")：" + ("已登录" if logged_in else "未登录，请在弹出的浏览器里扫码登录"),
            "info",
        )
        return logged_in

    def _close_impl(self):
        for obj in (self._page, self._context):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def _check_login_impl(self):
        try:
            names = {c["name"] for c in self._context.cookies()}
            if names & {"sessionid", "sid_guard", "sid_ucp_virtual", "sessionid_ss"}:
                return True
            url = self._page.url or ""
            return "douyin.com" in url and "/passport" not in url and "/login" not in url
        except Exception:
            return False

    def _get_chats_impl(self):
        if not self._check_login_impl():
            return []
        names = []
        try:
            els = self._page.query_selector_all("[class='conversationConversationItemtitle']")
            for el in els[:40]:
                t = (el.inner_text() or "").strip()
                if t and t not in names:
                    names.append(t)
        except Exception:
            pass
        return names

    def _current_chat_name(self):
        for sel in (
            "[class*='curConversation'] [class='conversationConversationItemtitle']",
            "[class*='RightPanelHeader'] [class*='user']",
        ):
            try:
                el = self._page.query_selector(sel)
                if el:
                    t = (el.inner_text() or "").strip()
                    if t:
                        return t
            except Exception:
                continue
        return "当前会话"

    def _poll_impl(self):
        if self._page is None or self._page.is_closed():
            self.log("浏览器已被关闭，如需继续请重新点「连接」", "error")
            self._connected = False
            return []
        if not self._check_login_impl():
            return []
        # 未打开任何会话时（无输入框），自动点开第一个会话
        if self._page.query_selector("[data-slate-editor='true']") is None:
            items = self._page.query_selector_all("[class*='conversationConversationItemwrapper']")
            if items:
                try:
                    items[0].click()
                    time.sleep(2.5)
                except Exception:
                    pass
        chat = self._current_chat_name()
        now = time.time()
        out = []
        try:
            msgs = self._page.evaluate(EXTRACT_MESSAGES_JS)
        except Exception:
            return out
        for m in msgs or []:
            text = (m.get("text") or "").strip()
            is_self = bool(m.get("self"))
            if not text or is_self:
                continue
            if text in self._sent:
                continue
            key = hashlib.md5(f"{chat}|{text}".encode("utf-8")).hexdigest()
            if self._seen.get(key, 0) > now:
                continue
            self._seen[key] = now + 60
            if len(self._seen) > 2000:
                self._seen = {k: v for k, v in self._seen.items() if v > now}
            out.append(IncomingMessage(
                chat=chat, sender=chat, content=text,
                is_group=False, is_self=False, is_at=False, ts=now,
            ))
        return out

    def _recent_messages_impl(self, limit=10):
        if self._page is None or self._page.is_closed():
            return []
        if not self._check_login_impl():
            return []
        try:
            msgs = self._page.evaluate(EXTRACT_MESSAGES_JS)
        except Exception:
            return []
        out = []
        for m in (msgs or [])[-limit:]:
            out.append((bool(m.get("self")), (m.get("text") or "").strip()))
        return out

    def _switch_conversation(self, name):
        items = self._page.query_selector_all("[class*='conversationConversationItemwrapper']")
        for item in items:
            try:
                title_el = item.query_selector("[class='conversationConversationItemtitle']")
                t = (title_el.inner_text() or "").strip() if title_el else ""
                if t and (t == name or name in t or t in name):
                    item.click()
                    return True
            except Exception:
                continue
        return False

    def _send_impl(self, chat, text):
        if self._page is None or self._page.is_closed():
            raise RuntimeError("浏览器已被关闭，请重新点「连接」")
        if not self._check_login_impl():
            raise RuntimeError("尚未登录抖音，请先在浏览器里扫码登录")
        # 若指定了会话且与当前不同，先切换
        if chat and chat != "当前会话":
            cur = self._current_chat_name()
            if chat != cur:
                try:
                    self._switch_conversation(chat)
                    time.sleep(1.5)
                except Exception:
                    pass
        # 点击 Slate 编辑器
        editor = self._page.query_selector("[data-slate-editor='true']")
        if editor is None:
            editor = self._page.query_selector("[contenteditable='true']")
        if editor is None:
            raise RuntimeError("未找到输入框，请确认私信会话已打开")
        editor.click()
        time.sleep(0.3)
        # 输入文本（insert_text 快，失败则逐字符输入）
        self._page.keyboard.insert_text(text)
        time.sleep(0.4)
        cur = ""
        try:
            e2 = self._page.query_selector("[data-slate-editor='true']")
            if e2:
                cur = (e2.inner_text() or "").strip()
        except Exception:
            pass
        if text not in cur:
            editor.click()
            self._page.keyboard.type(text, delay=15)
            time.sleep(0.4)
        # 点击发送按钮
        sent = False
        for sel in (".e2e-send-msg-btn", "[class*='messageMsgInputpublishBtn']", "[class*='publishBtn']"):
            try:
                btn = self._page.query_selector(sel)
                if btn:
                    btn.click()
                    sent = True
                    break
            except Exception:
                continue
        if not sent:
            self._page.keyboard.press("Enter")
