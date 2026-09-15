

class TaskRegistry:
    def __init__(self):
        self._handlers = {}

    def register(self, task_type: str):
        def decorator(fn):
            self._handlers[task_type] = fn
            return fn
        return decorator

    def get_handler(self, task_type: str):
        handler = self._handlers.get(task_type)
        if handler is None:
            raise ValueError(f"No handler registered for task type: {task_type}")
        return handler

    def has_handler(self, task_type: str) -> bool:
        return task_type in self._handlers
