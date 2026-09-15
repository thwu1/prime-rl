"""Circuit breaker for emergency bypass of policy checks.

When the failure threshold is exceeded, the circuit breaker opens and
PolicyChecker.check_quota should return an allow-all response without
attempting to access the data store.

The circuit breaker can also be manually opened via the trip() method,
which serves as a "red button" for emergency incident mitigation.
"""

import time
import threading


class CircuitBreaker:

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "closed"          # closed | open | half-open
        self._manual_override = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Return True when the circuit breaker is open (bypass mode)."""
        with self._lock:
            if self._manual_override:
                return True
            if self._state == "open":
                if time.time() - self._last_failure_time > self.recovery_timeout:
                    self._state = "half-open"
                    return False
                return True
            return False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_failure(self):
        """Record a single failure.  Opens the breaker after threshold."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = "open"

    def record_success(self):
        """Record a success.  Resets the breaker if half-open."""
        with self._lock:
            self._failure_count = 0
            if self._state == "half-open":
                self._state = "closed"

    # ------------------------------------------------------------------
    # Manual controls ("red button")
    # ------------------------------------------------------------------

    def trip(self):
        """Manually force the circuit breaker open (red-button override)."""
        with self._lock:
            self._manual_override = True
            self._state = "open"

    def reset(self):
        """Reset the circuit breaker to a healthy closed state."""
        with self._lock:
            self._manual_override = False
            self._failure_count = 0
            self._state = "closed"
