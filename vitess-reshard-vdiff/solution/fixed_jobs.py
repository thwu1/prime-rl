"""
Batch job implementations for user management (optimized).
Fixes the O(shards * channels) query explosion in forget_user.
"""
import sqlite3


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
    Remove a user and deactivate all their thread subscriptions.

    Optimized to use O(shards) queries instead of O(shards * channels):
    - Single bulk UPDATE per shard to deactivate all subscriptions
    - No per-channel iteration
    - No notifications sent to deactivated users
    """
    query_count = 0
    total_deactivated = 0

    # Deactivate the user across all shards
    for conn in shard_connections.values():
        conn.execute(
            "UPDATE users SET status = 'deactivated' WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        query_count += 1

    # Deactivate ALL thread subscriptions in a single query per shard
    for conn in shard_connections.values():
        cursor = conn.execute(
            "UPDATE thread_subscriptions SET status = 'inactive' "
            "WHERE user_id = ? AND status = 'active'",
            (user_id,)
        )
        total_deactivated += cursor.rowcount
        conn.commit()
        query_count += 1

    # No notifications: user is deactivated and has no connected clients

    return {
        'deactivated_subs': total_deactivated,
        'query_count': query_count,
        'notifications_sent': 0,
    }
