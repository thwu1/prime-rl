from __future__ import annotations

import json
from pathlib import Path

import pytest
import sandoq_pool_cleanup as cleanup


def _write_jsonl(path: Path, rows: list[dict[str, object]], *, partial_tail: bytes = b"") -> None:
    path.write_bytes(b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows) + partial_tail)
    path.chmod(0o600)


def test_recorded_sessions_use_durable_wal_as_live_authority(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    _write_jsonl(
        tmp_path / "pool_events.jsonl",
        [
            {"event": "outer_created", "outer_session_id": "deleted"},
            {"event": "outer_created", "outer_session_id": "event-only"},
        ],
        partial_tail=b'{"event":"outer_created"',
    )
    wal = tmp_path / "pool.wal.jsonl"
    _write_jsonl(
        wal,
        [
            {"event": "outer_created", "outer_session_id": "deleted"},
            {"event": "outer_deleted", "outer_session_id": "deleted"},
            {"event": "outer_created", "outer_session_id": "wal-only"},
        ],
    )

    assert cleanup._recorded_outer_session_ids(tmp_path, wal_path=wal, live_only=True) == [
        "event-only",
        "wal-only",
    ]
    assert cleanup._recorded_outer_session_ids(tmp_path, wal_path=wal) == [
        "deleted",
        "event-only",
        "wal-only",
    ]


def test_wal_cleans_complete_prefix_then_reports_incomplete_tail(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    wal = tmp_path / "pool.wal.jsonl"
    _write_jsonl(
        wal,
        [{"event": "outer_created", "outer_session_id": "known"}],
        partial_tail=b'{"event":"outer_created"',
    )
    incomplete: list[bool] = []

    assert cleanup._recorded_outer_session_ids(
        tmp_path,
        wal_path=wal,
        live_only=True,
        incomplete_wal=incomplete,
    ) == ["known"]
    assert incomplete == [True]

    with pytest.raises(cleanup.CleanupError, match="^pool_wal_invalid$"):
        cleanup._recorded_outer_session_ids(tmp_path, wal_path=wal)
