
from abc import ABC, abstractmethod
from typing import Optional


class Scheduler(ABC):
    """Abstract base class for LLM inference request schedulers.

    The simulator calls set_memory() before the first scheduling decision,
    giving the scheduler access to page-level memory state.
    """

    def set_memory(self, memory) -> None:
        """Called by the simulator to provide the paged memory manager."""
        self._memory = memory

    @abstractmethod
    def add_request(self, request) -> None:
        """Called when a new request arrives."""

    @abstractmethod
    def get_next(self) -> Optional[object]:
        """Return the next Request to run, or None if nothing is ready."""

    @abstractmethod
    def on_token_generated(self, request) -> bool:
        """Called after each output token.
        Return True  to keep running this request.
        Return False to preempt (on_preempt will be called next)."""

    @abstractmethod
    def on_preempt(self, request) -> None:
        """Called when the running request is preempted."""

    @abstractmethod
    def on_complete(self, request) -> None:
        """Called when a request finishes all output tokens."""

    @abstractmethod
    def has_pending(self) -> bool:
        """True if any request is pending or in progress."""
