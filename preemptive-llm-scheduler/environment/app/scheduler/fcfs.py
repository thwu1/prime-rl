
from collections import deque
from scheduler.base import Scheduler


class FCFSScheduler(Scheduler):
    """First-Come-First-Served: no preemption, run each request to completion."""

    def __init__(self):
        self.queue = deque()
        self.current = None

    def add_request(self, request):
        self.queue.append(request)

    def get_next(self):
        if self.current is not None and not self.current.is_complete:
            return self.current
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        return None

    def on_token_generated(self, request):
        return True  # never preempt

    def on_preempt(self, request):
        pass

    def on_complete(self, request):
        self.current = None

    def has_pending(self):
        return bool(self.queue) or (
            self.current is not None and not self.current.is_complete
        )
