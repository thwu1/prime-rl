
from enum import Enum
from typing import Any, Optional


class ErrorKind(Enum):
    RECOVERABLE = "recoverable"
    UNRECOVERABLE = "unrecoverable"


class TaskResult:
    __slots__ = ("_success", "_error_kind", "_message", "_data")

    def __init__(self, success: bool, error_kind=None, message="", data=None):
        self._success = success
        self._error_kind = error_kind
        self._message = message
        self._data = data

    @classmethod
    def ok(cls, data=None):
        return cls(True, data=data)

    @classmethod
    def fail(cls, error_kind=ErrorKind.RECOVERABLE, message=""):
        return cls(False, error_kind=error_kind, message=message)

    @property
    def success(self) -> bool:
        return self._success

    @property
    def error_kind(self) -> Optional[ErrorKind]:
        return self._error_kind

    @property
    def message(self) -> str:
        return self._message

    @property
    def data(self) -> Any:
        return self._data
