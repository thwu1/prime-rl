"""
Forget User Job — deactivates a user and removes their thread subscriptions.

WARNING: This implementation contains the same cascading-query bug described
in Slack's "The Query Strikes Again" blog post (Oct 2022 incident).  When
processing a user deletion it:

  1.  Queries ALL thread subscriptions for the user across ALL channels.
  2.  For each channel being left, issues an UPDATE whose IN-clause contains
      every subscription ID the user has — not just the ones for the current
      channel.
  3.  After each channel update, queries all subscriptions again to "send
      client notifications" — unnecessary for a deactivated user.

This causes O(channels²) database load instead of O(channels).
"""

import sys
sys.path.insert(0, "/app")
from shard_manager import ShardManager


def forget_user(user_id: int, workspace_id: int) -> dict:
    """Deactivate *user_id* and unsubscribe from all threads.

    Returns a stats dict with keys ``channels_processed``,
    ``subs_deactivated``, and ``queries_executed``.
    """
    mgr = ShardManager()
    shard = mgr.route_query("users", workspace_id)
    conn = mgr.get_connection(shard)

    stats = {
        "channels_processed": 0,
        "subs_deactivated": 0,
        "queries_executed": 0,
    }

    # Deactivate the user
    conn.execute(
        "UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    stats["queries_executed"] += 1

    # Get all channels with active subscriptions
    channels = conn.fetchall(
        "SELECT DISTINCT channel_id FROM thread_subscriptions "
        "WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    stats["queries_executed"] += 1

    for ch in channels:
        channel_id = ch["channel_id"]

        # BUG: fetches ALL subs across ALL channels, not just this one
        all_subs = conn.fetchall(
            "SELECT sub_id, channel_id FROM thread_subscriptions "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        stats["queries_executed"] += 1

        # BUG: passes every sub_id even though WHERE also filters by channel
        all_sub_ids = [s["sub_id"] for s in all_subs]
        if all_sub_ids:
            ph = ",".join(["?" for _ in all_sub_ids])
            conn.execute(
                f"UPDATE thread_subscriptions SET is_active = 0 "
                f"WHERE sub_id IN ({ph}) AND channel_id = ?",
                (*all_sub_ids, channel_id),
            )
            conn.commit()
            stats["queries_executed"] += 1
            stats["subs_deactivated"] += sum(
                1 for s in all_subs if s["channel_id"] == channel_id
            )

        # BUG: queries everything again to "notify connected clients"
        # (pointless for a deactivated user who cannot be connected)
        conn.fetchall(
            "SELECT sub_id FROM thread_subscriptions "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        stats["queries_executed"] += 1

        stats["channels_processed"] += 1

    mgr.close_all()
    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Forget (deactivate) a user")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--workspace-id", type=int, required=True)
    args = parser.parse_args()

    result = forget_user(args.user_id, args.workspace_id)
    print(f"Forget user complete: {result}")
