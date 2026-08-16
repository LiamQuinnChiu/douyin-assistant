"""后台线程：消息轮询与回复处理。"""
import threading
import time


class Poller(threading.Thread):
    """周期轮询消息，放入 incoming_q。"""

    def __init__(self, adapter, incoming_q, log=None, interval=0.8):
        super().__init__(daemon=True, name="douyin-poller")
        self.adapter = adapter
        self.incoming_q = incoming_q
        self.log = log or (lambda *a, **k: None)
        self.interval = max(0.2, float(interval))
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                if self.adapter.is_connected():
                    for msg in self.adapter.poll_messages():
                        self.incoming_q.put(msg)
            except Exception as e:
                self.log(f"轮询异常: {e}", "error")
            time.sleep(self.interval)


class ReplyWorker(threading.Thread):
    """消费 incoming_q，交给 Brain 处理，结果放入 events_q 由 GUI 线程发送。"""

    def __init__(self, brain, incoming_q, events_q, log=None):
        super().__init__(daemon=True, name="reply-worker")
        self.brain = brain
        self.incoming_q = incoming_q
        self.events_q = events_q
        self.log = log or (lambda *a, **k: None)

    def run(self):
        while True:
            msg = self.incoming_q.get()
            if msg is None:
                return
            self.events_q.put(("recv", msg))
            try:
                reply = self.brain.handle(msg)
            except Exception as e:
                self.log(f"处理消息出错: {e}", "error")
                continue
            if reply:
                self.events_q.put(("reply", msg, reply))
