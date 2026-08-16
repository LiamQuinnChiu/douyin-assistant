"""主窗口：连接聊天平台（抖音私信等）、配置模型、查看消息、手动发送。"""
import html
import queue
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from bot.adapters.douyin_adapter import DouyinAdapter
from bot.brain import Brain
from bot.llm import LLMClient
from bot.worker import Poller, ReplyWorker

ADAPTERS = {DouyinAdapter.name: DouyinAdapter}


def _ts():
    return time.strftime("%H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.adapter = None
        self.brain = None
        self.poller = None
        self.reply_worker = None
        self.incoming_q = queue.Queue()
        self.events_q = queue.Queue()
        self.log_q = queue.Queue()
        self._loading = False
        self._updating_chats = False

        self.setWindowTitle("抖音助手")
        self.resize(1120, 720)
        self._build_ui()
        self._restore_settings()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(200)

        self._append_log("info", "欢迎使用抖音助手。请先在右侧填写模型配置，再点「连接」。")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 顶部工具栏
        bar = QHBoxLayout()
        bar.addWidget(QLabel("后端:"))
        self.backend_combo = QComboBox()
        for name, cls in ADAPTERS.items():
            self.backend_combo.addItem(cls.display_name, name)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_change)
        bar.addWidget(self.backend_combo)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connect)
        bar.addWidget(self.connect_btn)
        self.master_switch = QCheckBox("开启自动回复")
        self.master_switch.toggled.connect(self._on_master_switch)
        bar.addWidget(self.master_switch)
        bar.addStretch(1)
        self.status_label = QLabel("未连接")
        bar.addWidget(self.status_label)
        root.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # 左：会话列表
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("会话列表（勾选 = 允许自动回复）"))
        self.chat_list = QListWidget()
        self.chat_list.itemChanged.connect(self.on_chat_item_changed)
        lv.addWidget(self.chat_list, 1)
        self.refresh_btn = QPushButton("刷新会话")
        self.refresh_btn.clicked.connect(self.refresh_chats)
        lv.addWidget(self.refresh_btn)
        splitter.addWidget(left)

        # 中：消息记录 + 发送框
        mid = QWidget()
        mv = QVBoxLayout(mid)
        header = QHBoxLayout()
        header.addWidget(QLabel("消息记录"))
        header.addStretch(1)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.log_view_clear)
        header.addWidget(clear_btn)
        mv.addLayout(header)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        mv.addWidget(self.log_view, 1)
        send_row = QHBoxLayout()
        send_row.addWidget(QLabel("发送到:"))
        self.send_target = QComboBox()
        self.send_target.setEditable(True)
        send_row.addWidget(self.send_target, 1)
        self.send_text_edit = QLineEdit()
        self.send_text_edit.setPlaceholderText("输入要发送的消息，回车发送")
        self.send_text_edit.returnPressed.connect(self.manual_send)
        send_row.addWidget(self.send_text_edit, 2)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.manual_send)
        send_row.addWidget(self.send_btn)
        self.compose_btn = QPushButton("生成回复")
        self.compose_btn.setToolTip("结合当前会话上下文生成一条回复并发送（对方没发新消息也能用）")
        self.compose_btn.clicked.connect(self.manual_compose)
        send_row.addWidget(self.compose_btn)
        mv.addLayout(send_row)
        splitter.addWidget(mid)

        # 右：设置
        right = QTabWidget()
        right.addTab(self._build_llm_tab(), "模型设置")
        right.addTab(self._build_rules_tab(), "回复规则")
        right.addTab(self._build_persona_tab(), "人设提示词")
        splitter.addWidget(right)
        splitter.setSizes([240, 480, 340])

    def _build_llm_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.ed_base_url = QLineEdit()
        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.Password)
        self.ed_model = QLineEdit()
        self.sp_temperature = QDoubleSpinBox()
        self.sp_temperature.setRange(0.0, 2.0)
        self.sp_temperature.setSingleStep(0.1)
        self.sp_temperature.setDecimals(2)
        self.sp_max_tokens = QSpinBox()
        self.sp_max_tokens.setRange(1, 8192)
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(10, 600)
        form.addRow("接口地址", self.ed_base_url)
        form.addRow("API Key", self.ed_api_key)
        form.addRow("模型名称", self.ed_model)
        form.addRow("温度", self.sp_temperature)
        form.addRow("最大输出", self.sp_max_tokens)
        form.addRow("超时(秒)", self.sp_timeout)

        self.ed_base_url.textChanged.connect(lambda v: self._save("llm.base_url", v))
        self.ed_api_key.textChanged.connect(lambda v: self._save("llm.api_key", v))
        self.ed_model.textChanged.connect(lambda v: self._save("llm.model", v))
        self.sp_temperature.valueChanged.connect(lambda v: self._save("llm.temperature", v))
        self.sp_max_tokens.valueChanged.connect(lambda v: self._save("llm.max_tokens", v))
        self.sp_timeout.valueChanged.connect(lambda v: self._save("llm.timeout_seconds", v))

        self.test_btn = QPushButton("测试模型连接")
        self.test_btn.clicked.connect(self.test_model)
        form.addRow("", self.test_btn)
        hint = QLabel("接口需兼容 OpenAI Chat Completions 协议，如 DeepSeek、OpenAI、通义千问等。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888")
        form.addRow(hint)
        return w

    def _build_rules_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.ck_only_at = QCheckBox("群聊中仅在被 @ 时回复（更安全，推荐开启）")
        self.ck_only_at.toggled.connect(lambda v: self._save("auto_reply.only_at_me_in_groups", bool(v)))
        v.addWidget(self.ck_only_at)

        form = QFormLayout()
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(0, 60)
        self.sp_interval.setSuffix(" 秒")
        self.sp_context = QSpinBox()
        self.sp_context.setRange(0, 50)
        self.sp_poll = QDoubleSpinBox()
        self.sp_poll.setRange(0.3, 5.0)
        self.sp_poll.setSingleStep(0.1)
        self.sp_poll.setDecimals(1)
        self.ed_blacklist = QLineEdit()
        form.addRow("回复最小间隔", self.sp_interval)
        form.addRow("上下文记忆轮数", self.sp_context)
        form.addRow("消息轮询间隔", self.sp_poll)
        form.addRow("黑名单关键词", self.ed_blacklist)
        v.addLayout(form)

        self.sp_interval.valueChanged.connect(lambda v: self._save("auto_reply.min_interval_seconds", v))
        self.sp_context.valueChanged.connect(lambda v: self._save("auto_reply.max_context_turns", v))
        self.sp_poll.valueChanged.connect(lambda v: self._save("bot.poll_interval", v))
        self.ed_blacklist.textChanged.connect(self._on_blacklist_change)

        btn = QPushButton("清空全部上下文记忆")
        btn.clicked.connect(self.clear_memory)
        v.addWidget(btn)
        hint = QLabel("黑名单关键词用逗号分隔；命中任意一个则不回复。轮询间隔需重连后生效。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888")
        v.addWidget(hint)
        v.addStretch(1)
        return w

    def _build_persona_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("系统提示词（机器人的人设与回复风格）:"))
        self.ed_persona = QPlainTextEdit()
        self.ed_persona.setPlaceholderText("例如：你是一个乐于助人的抖音客服助手……")
        self.ed_persona.textChanged.connect(self._on_persona_change)
        v.addWidget(self.ed_persona, 1)
        return w

    # ------------------------------------------------------------ 配置回写
    def _save(self, dotted, value):
        if self._loading:
            return
        self.config.set(dotted, value)
        self.config.save()

    def _on_persona_change(self):
        if self._loading:
            return
        self.config.set("persona", self.ed_persona.toPlainText())
        self.config.save()

    def _on_blacklist_change(self):
        if self._loading:
            return
        kws = [k.strip() for k in self.ed_blacklist.text().split(",") if k.strip()]
        self.config.set("auto_reply.blacklist_keywords", kws)
        self.config.save()

    def _restore_settings(self):
        self._loading = True
        idx = self.backend_combo.findData(self.config.get("bot.backend", "douyin"))
        self.backend_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ed_base_url.setText(self.config.get("llm.base_url"))
        self.ed_api_key.setText(self.config.get("llm.api_key"))
        self.ed_model.setText(self.config.get("llm.model"))
        self.sp_temperature.setValue(self.config.get("llm.temperature"))
        self.sp_max_tokens.setValue(self.config.get("llm.max_tokens"))
        self.sp_timeout.setValue(self.config.get("llm.timeout_seconds"))
        self.master_switch.setChecked(self.config.get("auto_reply.enabled"))
        self.ck_only_at.setChecked(self.config.get("auto_reply.only_at_me_in_groups"))
        self.sp_interval.setValue(self.config.get("auto_reply.min_interval_seconds"))
        self.sp_context.setValue(self.config.get("auto_reply.max_context_turns"))
        self.sp_poll.setValue(self.config.get("bot.poll_interval"))
        self.ed_blacklist.setText(", ".join(self.config.get("auto_reply.blacklist_keywords", [])))
        self.ed_persona.setPlainText(self.config.get("persona"))
        self._loading = False

    # ------------------------------------------------------------ 事件处理
    def _on_backend_change(self, idx):
        if self._loading or idx < 0:
            return
        self.config.set("bot.backend", self.backend_combo.itemData(idx))
        self.config.save()

    def _on_master_switch(self, checked):
        if self._loading:
            return
        self.config.set("auto_reply.enabled", bool(checked))
        self.config.save()
        self._append_log("info", "自动回复已开启" if checked else "自动回复已关闭")

    def toggle_connect(self):
        if self.adapter and self.adapter.is_connected():
            self.disconnect_all()
            return
        cls = ADAPTERS[self.backend_combo.currentData()]
        self._append_log("info", f"正在连接后端: {cls.display_name} …")
        if cls.name == "douyin":
            from pathlib import Path
            profile_dir = Path(__file__).resolve().parent.parent / ".douyin_profile"
            adapter = cls(log=self._log_async, profile_dir=str(profile_dir))
        else:
            adapter = cls(log=self._log_async)
        try:
            adapter.connect()
        except Exception as e:
            self._append_log("error", f"连接失败: {e}")
            QMessageBox.warning(
                self, "连接失败",
                f"{e}\n\n常见原因：\n1. 浏览器未正常打开或未登录抖音\n"
                "2. 缺少依赖：pip install -r requirements.txt\n"
                "3. 网络异常或页面结构变化",
            )
            return
        self.adapter = adapter
        self.status_label.setText(f"已连接 · {cls.display_name}")
        self.connect_btn.setText("断开连接")
        self._append_log("info", "连接成功")

        self.brain = Brain(self.config, LLMClient(self.config), log=self._log_async)
        interval = self.config.get("bot.poll_interval", 2.0)
        self.poller = Poller(adapter, self.incoming_q, log=self._log_async, interval=interval)
        self.reply_worker = ReplyWorker(self.brain, self.incoming_q, self.events_q, log=self._log_async)
        self.poller.start()
        self.reply_worker.start()
        self.refresh_chats()

    def disconnect_all(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        if self.adapter:
            try:
                self.adapter.disconnect()
            except Exception as e:
                self._append_log("error", f"断开异常: {e}")
        self.adapter = None
        self.status_label.setText("未连接")
        self.connect_btn.setText("连接")
        self._append_log("info", "已断开连接")

    def refresh_chats(self):
        if not self.adapter or not self.adapter.is_connected():
            self._append_log("error", "请先连接")
            return
        try:
            chats = self.adapter.get_chats()
        except Exception as e:
            self._append_log("error", f"获取会话列表失败: {e}")
            return
        chats_cfg = self.config.get("auto_reply.chats", {})
        self._updating_chats = True
        self.chat_list.clear()
        self.send_target.clear()
        for name in sorted(chats):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            enabled = bool(chats_cfg.get(name, {}).get("enabled"))
            item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
            self.chat_list.addItem(item)
            self.send_target.addItem(name)
        self._updating_chats = False
        self._sync_listen_chats()
        self._append_log("info", f"已加载 {len(chats)} 个会话")

    def on_chat_item_changed(self, item):
        if self._updating_chats:
            return
        name = item.text()
        checked = item.checkState() == Qt.Checked
        chats = self.config.get("auto_reply.chats", {})
        chats[name] = {"enabled": checked}
        self.config.save()
        self._sync_listen_chats()
        self._append_log("info", f"已{'启用' if checked else '停用'}自动回复: {name}")

    def _sync_listen_chats(self):
        if not self.adapter:
            return
        chats_cfg = self.config.get("auto_reply.chats", {})
        enabled = [n for n, c in chats_cfg.items() if c.get("enabled")]
        try:
            self.adapter.set_listen_chats(enabled)
        except Exception:
            pass

    def manual_send(self):
        target = self.send_target.currentText().strip()
        text = self.send_text_edit.text().strip()
        if not target:
            QMessageBox.information(self, "提示", "请选择发送对象")
            return
        if not text:
            return
        if not self.adapter or not self.adapter.is_connected():
            QMessageBox.warning(self, "提示", "请先连接")
            return
        self._do_send(target, text)
        self.send_text_edit.clear()

    def manual_compose(self):
        """手动生成回复：结合当前会话上下文生成一条回复并发送。"""
        target = self.send_target.currentText().strip()
        if not target:
            QMessageBox.information(self, "提示", "请选择发送对象")
            return
        if not self.adapter or not self.adapter.is_connected():
            QMessageBox.warning(self, "提示", "请先连接")
            return
        self._append_log("info", f"正在结合上下文为 [{target}] 生成回复 …")

        def run():
            try:
                msgs = self.adapter.get_recent_messages(12)
                lines = ["下面是最近的聊天记录（对方=对方发的，我=你发的）："]
                for is_self, text in msgs:
                    lines.append(("我：" if is_self else "对方：") + text)
                lines.append("")
                lines.append("请结合上面的聊天上下文，以 我 的身份，主动回复一条合适、自然的消息。只输出回复内容本身，不要任何解释、引号或标注。")
                prompt = "\n".join(lines)
                llm = LLMClient(self.config)
                reply = llm.chat([
                    {"role": "system", "content": self.config.get("persona") or ""},
                    {"role": "user", "content": prompt},
                ]).strip()
                if not reply:
                    self._log_async("生成回复为空", "error")
                    return
                self.events_q.put(("manual_send", target, reply))
            except Exception as e:
                self._log_async(f"生成回复失败: {e}", "error")

        threading.Thread(target=run, daemon=True).start()

    def test_model(self):
        self.test_btn.setEnabled(False)

        def run():
            try:
                llm = LLMClient(self.config)
                reply = llm.chat([{"role": "user", "content": "请只回复四个字：连接成功"}])
                self._log_async(f"模型测试成功：{reply}", "info")
            except Exception as e:
                self._log_async(f"模型测试失败：{e}", "error")
            finally:
                self.log_q.put(("test_done", ""))

        threading.Thread(target=run, daemon=True).start()

    def clear_memory(self):
        if getattr(self, "brain", None):
            self.brain.reset_memory()
        self._append_log("info", "已清空全部上下文记忆")

    def log_view_clear(self):
        self.log_view.clear()

    # ------------------------------------------------------------ 线程与输出
    def _log_async(self, text, kind="info"):
        """供工作线程安全调用。"""
        self.log_q.put((kind, text))

    def _tick(self):
        try:
            while True:
                kind, text = self.log_q.get_nowait()
                if kind == "test_done":
                    self.test_btn.setEnabled(True)
                else:
                    self._append_log(kind, text)
        except queue.Empty:
            pass
        try:
            while True:
                self._handle_event(self.events_q.get_nowait())
        except queue.Empty:
            pass

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "recv":
            msg = ev[1]
            if msg.is_group:
                line = f"【群】{msg.chat} · {msg.sender}: {msg.content}"
            else:
                line = f"{msg.chat}: {msg.content}"
            self._append_log("recv", line)
        elif kind == "reply":
            _, msg, reply = ev
            self._append_log("reply", f"AI → {msg.chat}: {reply}")
            self._do_send(msg.chat, reply)
        elif kind == "manual_send":
            _, target, reply = ev
            self._append_log("reply", f"AI → {target}: {reply}")
            self._do_send(target, reply)

    def _do_send(self, chat, text):
        if not self.adapter or not self.adapter.is_connected():
            self._append_log("error", f"发送失败（未连接）→ {chat}")
            return
        try:
            self.adapter.send_text(chat, text)
            self._append_log("send", f"已发送 → {chat}")
        except Exception as e:
            self._append_log("error", f"发送失败 → {chat}: {e}")

    def _append_log(self, kind, text):
        colors = {
            "info": "#888888",
            "recv": "#2962ff",
            "reply": "#2e7d32",
            "send": "#6a1b9a",
            "error": "#c62828",
        }
        color = colors.get(kind, "#333333")
        esc = html.escape(text)
        self.log_view.append(
            f'<span style="color:#999999">[{_ts()}]</span> '
            f'<span style="color:{color}">{esc}</span>'
        )
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        self.disconnect_all()
        super().closeEvent(event)
