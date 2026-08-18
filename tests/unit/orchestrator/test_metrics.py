import uuid

import pandas as pd
import pytest

from prime_rl.orchestrator.metrics import _compute_solve_rates


def test_solve_rates_use_positive_reward_as_solved():
    groups = [uuid.uuid4() for _ in range(3)]
    df = pd.DataFrame(
        {
            "group_id": [groups[0], groups[0], groups[0], groups[1], groups[1], groups[1], groups[2], groups[2], groups[2]],
            "env_name": ["tb"] * 9,
            "reward": [-0.05, 0.0, -0.05, 0.95, 0.0, -0.05, 1.0, 0.95, 1.0],
        }
    )

    solve_none, solve_all, effective_batch_size = _compute_solve_rates(df, {"tb": 3})

    assert solve_none == 1 / 3
    assert solve_all == 1 / 3
    assert effective_batch_size == pytest.approx(1 / 3)
