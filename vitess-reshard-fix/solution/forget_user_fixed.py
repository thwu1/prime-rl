"""
Fixed Forget User Job.

Changes from the buggy version:
  1. Queries only subscriptions for the *current* channel (not all channels).
  2. UPDATE only includes sub_ids for the current channel.
  3. Skips the redundant "notify clients" re-query (user is deactivated).
  4. Accepts ``max_ops_per_sec`` for rate limiting.
  5. Checks ``monitor.is_healthy()`` before each channel (circuit breaker).
"""

import sys
import time

sys.path.insert(0, "/app")
from shard_manager import ShardManager
from monitor import monitor


def forget_user(
    user_id: int,
    workspace_id: int,
    max_ops_per_sec: int = 10,
    error_threshold: float = 0.5,
) -> dict:
    """Deactivate *user_id* and unsubscribe from all threads.

    Parameters
    ----------
    max_ops_per_sec : int
        Maximum channel iterations per second (rate limiting).
    error_threshold : float
        Error-rate threshold passed to ``monitor.is_healthy()``.
    """
    mgr = ShardManager()
    shard = mgr.route_query("users", workspace_id)
    conn = mgr.get_connection(shard)

    stats = {
        "channels_processed": 0,
        "subs_deactivated": 0,
        "queries_executed": 0,
        "circuit_breaker_tripped": False,
    }

    # Deactivate user
    conn.execute(
        "UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    stats["queries_executed"] += 1

    # Distinct channels with active subscriptions
    channels = conn.fetchall(
        "SELECT DISTINCT channel_id FROM thread_subscriptions "
        "WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    stats["queries_executed"] += 1

    interval = 1.0 / max_ops_per_sec if max_ops_per_sec > 0 else 0

    for ch in channels:
        # ── Circuit breaker ─────────────────────────────────────────────
        if not monitor.is_healthy(shard, error_threshold):
            stats["circuit_breaker_tripped"] = True
            break

        channel_id = ch["channel_id"]

        # FIX: query only subs for THIS channel
        channel_subs = conn.fetchall(
            "SELECT sub_id FROM thread_subscriptions "
            "WHERE user_id = ? AND channel_id = ? AND is_active = 1",
            (user_id, channel_id),
        )
        stats["queries_executed"] += 1

        if channel_subs:
            sub_ids = [s["sub_id"] for s in channel_subs]
            ph = ",".join(["?"] * len(sub_ids))
            conn.execute(
                f"UPDATE thread_subscriptions SET is_active = 0 "
                f"WHERE sub_id IN ({ph})",
                tuple(sub_ids),
            )
            conn.commit()
            stats["queries_executed"] += 1
            stats["subs_deactivated"] += len(sub_ids)

        # FIX: skip unnecessary client notification for deactivated user

        stats["channels_processed"] += 1

        # ── Rate limiting ───────────────────────────────────────────────
        if interval > 0:
            time.sleep(interval)

    mgr.close_all()
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--max-ops-per-sec", type=int, default=10)
    args = parser.parse_args()

    result = forget_user(
        args.user_id, args.workspace_id,
        max_ops_per_sec=args.max_ops_per_sec,
    )
    print(f"Forget user complete: {result}")
