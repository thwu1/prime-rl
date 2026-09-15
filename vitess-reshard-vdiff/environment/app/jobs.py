"""
Batch job implementations for user management.

The forget_user job handles removing a user from all channels and
deactivating their thread subscriptions when they are removed from
a workspace.
"""
import sqlite3


# Global notification log for tracking
_notification_log = []


def get_notification_log():
    """Return the notification log."""
    return list(_notification_log)


def clear_notification_log():
    """Clear the notification log."""
    global _notification_log
    _notification_log = []


def _send_notification(user_id, channel_id, sub_count):
    """Send a subscription update notification to the user's connected clients."""
    _notification_log.append({
        'user_id': user_id,
        'channel_id': channel_id,
        'updated_sub_count': sub_count,
    })


def forget_user(user_id, shard_connections):
    """
    Remove a user from all channels and deactivate their thread subscriptions.

    This is called when a user is removed from a workspace. It must:
    1. Deactivate the user
    2. For each channel the user is a member of, leave the channel
    3. Deactivate all thread subscriptions for the user

    Args:
        user_id: The ID of the user to forget
        shard_connections: Dict of shard_name -> sqlite3.Connection

    Returns:
        Dict with:
        - deactivated_subs: Total number of subscriptions deactivated
        - query_count: Total number of SQL queries executed
        - notifications_sent: Number of notifications sent
    """
    query_count = 0
    total_deactivated = 0

    # Deactivate the user
    for shard_name, conn in shard_connections.items():
        conn.execute(
            "UPDATE users SET status = 'deactivated' WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        query_count += 1

    # Get all channels the user is a member of
    user_channels = []
    for shard_name, conn in shard_connections.items():
        rows = conn.execute(
            "SELECT DISTINCT channel_id FROM channel_members WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        user_channels.extend([r[0] for r in rows])
        query_count += 1

    # For each channel, process the leave operation
    for channel_id in user_channels:
        for shard_name, conn in shard_connections.items():
            all_subs = conn.execute(
                "SELECT sub_id, channel_id FROM thread_subscriptions "
                "WHERE user_id = ? AND status = 'active'",
                (user_id,)
            ).fetchall()
            query_count += 1

            all_sub_ids = [s[0] for s in all_subs]

            if all_sub_ids:
                placeholders = ','.join(['?'] * len(all_sub_ids))
                conn.execute(
                    f"UPDATE thread_subscriptions SET status = 'inactive' "
                    f"WHERE channel_id = ? AND sub_id IN ({placeholders})",
                    [channel_id] + all_sub_ids
                )
                conn.commit()
                query_count += 1

                deactivated = sum(1 for s in all_subs if s[1] == channel_id)
                total_deactivated += deactivated

            _send_notification(user_id, channel_id, len(all_sub_ids))

    return {
        'deactivated_subs': total_deactivated,
        'query_count': query_count,
        'notifications_sent': len(_notification_log),
    }
