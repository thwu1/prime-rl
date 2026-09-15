"""
Linearizability checker for concurrent operation histories.

A history is linearizable if each operation can be assigned a
linearization point within its [invoke_time, response_time] interval
such that the resulting sequential history is consistent with the
sequential register specification.

The register spec:
  - initial value: history.initial_value
  - write(v) -> "ok": sets register to v
  - read() -> v: returns current register value

Crashed operations (response_time=None) may or may not have taken effect.

Implement the is_linearizable function below.
"""

from history import History


def is_linearizable(history: History) -> bool:
    """
    Check if the given history is linearizable with respect to a
    single-value register with read/write operations.

    The register starts at history.initial_value.
    Operations may be concurrent (overlapping time intervals).
    Some operations may have crashed (response_time and response_value are None).
    Crashed operations may or may not have taken effect.

    Returns True if the history is linearizable, False otherwise.
    """
    raise NotImplementedError("Implement the linearizability checker")
