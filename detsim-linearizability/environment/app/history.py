"""
Data structures for operation histories in linearizability checking.

Each Operation represents a single read or write on a register,
with invocation and response timestamps defining a real-time interval.
Crashed operations have response_time=None and response_value=None.
"""

import json
from dataclasses import dataclass
from typing import Optional, Any, List


@dataclass
class Operation:
    """A single operation in a concurrent history."""
    op_id: int
    op_type: str        # "read" or "write"
    arg: Optional[int]  # argument for write; None for read
    invoke_time: int    # when the operation was invoked
    response_time: Optional[int]   # when the response arrived; None if crashed
    response_value: Any            # int for read, "ok" for write, None if crashed


@dataclass
class History:
    """A concurrent operation history from a simulation run."""
    seed: str
    initial_value: int
    operations: List[Operation]

    @classmethod
    def from_json(cls, path: str) -> 'History':
        with open(path) as f:
            data = json.load(f)
        ops = [Operation(**op) for op in data["operations"]]
        return cls(
            seed=data["seed"],
            initial_value=data.get("initial_value", 0),
            operations=ops,
        )

    def to_json(self, path: str):
        data = {
            "seed": self.seed,
            "initial_value": self.initial_value,
            "operations": [
                {
                    "op_id": op.op_id,
                    "op_type": op.op_type,
                    "arg": op.arg,
                    "invoke_time": op.invoke_time,
                    "response_time": op.response_time,
                    "response_value": op.response_value,
                }
                for op in self.operations
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
