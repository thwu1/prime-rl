"""
Asset reconciliation module for determining which assets need re-materialization.

Provides functions to:
1. Build and topologically sort an asset dependency graph
2. Align partitions across different schemes (daily -> weekly)
3. Detect stale assets that need re-materialization
4. Compute a reconciliation plan with transitive staleness propagation
5. Validate partition completeness for weekly aggregation windows

"""

from datetime import datetime, timedelta
from collections import defaultdict, deque


ASSET_DEPS = {
    "raw_events": [], "raw_users": [], "raw_transactions": [],
    "cleaned_events": ["raw_events"],
    "cleaned_users": ["raw_users"],
    "cleaned_transactions": ["raw_transactions"],
    "daily_event_aggregates": ["cleaned_events"],
    "daily_user_metrics": ["cleaned_users"],
    "daily_transaction_summary": ["cleaned_transactions"],
    "hourly_event_counts": ["cleaned_events"],
    "user_profiles": ["cleaned_users"],
    "user_segments": ["cleaned_users", "cleaned_events"],
    "weekly_reports": [
        "daily_event_aggregates", "daily_user_metrics", "daily_transaction_summary"
    ],
    "monthly_summaries": ["weekly_reports"],
    "dashboard_cache": [
        "daily_event_aggregates", "user_profiles", "daily_transaction_summary"
    ],
}


def build_downstream_graph(asset_deps):
    """Build adjacency list: upstream -> list of downstream assets."""
    graph = defaultdict(list)
    for asset, deps in asset_deps.items():
        for dep in deps:
            graph[dep].append(asset)
    return dict(graph)


def topological_sort(asset_deps):
    """
    Topological sort of asset dependency graph using Kahn's algorithm.
    Returns assets in dependency order (roots first, leaves last).

    Args:
        asset_deps: dict mapping asset_key -> list of upstream asset_keys

    Returns:
        list of asset_keys in topological order
    """
    # Build in-degree map and downstream graph
    in_degree = {}
    graph = defaultdict(list)

    for asset, deps in asset_deps.items():
        in_degree[asset] = len(deps)
        for dep in deps:
            graph[dep].append(asset)

    # Find starting nodes (in-degree 0)
    queue = deque()
    for node in in_degree:
        if in_degree[node] == 0:
            queue.append(node)

    result = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for downstream in graph.get(node, []):
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)

    return result


def get_weekly_partition_for_daily(daily_partition_key):
    """
    Given a daily partition key (YYYY-MM-DD), return the corresponding
    weekly partition key (the Monday of that week, as YYYY-MM-DD).

    Args:
        daily_partition_key: str "YYYY-MM-DD"

    Returns:
        str: weekly partition key (Monday) "YYYY-MM-DD"
    """
    date = datetime.strptime(daily_partition_key, "%Y-%m-%d")
    monday = date - timedelta(days=date.isoweekday())
    return monday.strftime("%Y-%m-%d")


def get_daily_partitions_for_weekly(weekly_partition_key):
    """
    Given a weekly partition key (Monday), return all 7 daily partition keys.
    """
    monday = datetime.strptime(weekly_partition_key, "%Y-%m-%d")
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def find_stale_assets(asset_deps, materialization_times):
    """
    Find assets that need re-materialization because at least one upstream
    dependency has been materialized more recently.

    Args:
        asset_deps: dict mapping asset_key -> [upstream asset_keys]
        materialization_times: dict mapping asset_key -> latest materialization
                               timestamp (float)

    Returns:
        list of stale asset_keys
    """
    stale = []

    for asset, deps in asset_deps.items():
        if not deps:
            continue

        downstream_ts = materialization_times.get(asset)
        if downstream_ts is None:
            stale.append(asset)
            continue

        upstream_timestamps = []
        for dep in deps:
            ts = materialization_times.get(dep)
            if ts is not None:
                upstream_timestamps.append(ts)

        if not upstream_timestamps:
            continue

        if all(ts > downstream_ts for ts in upstream_timestamps):
            stale.append(asset)

    return stale


def validate_partition_completeness(weekly_partition_key, materialized_daily_partitions):
    """
    Check if all daily partitions within a weekly partition's window
    have been materialized.

    Args:
        weekly_partition_key: str "YYYY-MM-DD" (Monday of the week)
        materialized_daily_partitions: set of str "YYYY-MM-DD"

    Returns:
        bool: True if all daily partitions are present
    """
    monday = datetime.strptime(weekly_partition_key, "%Y-%m-%d")
    expected = set(
        (monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)
    )
    return expected.issubset(materialized_daily_partitions)


def compute_reconciliation_plan(asset_deps, materialization_times,
                                partition_schemes=None):
    """
    Compute which assets need re-materialization and in what order.

    Returns list of asset_keys in execution order (topological).
    Assets are included if they are directly stale or if any of their
    upstream dependencies are stale (transitive staleness).
    """
    topo_order = topological_sort(asset_deps)
    stale_assets = set(find_stale_assets(asset_deps, materialization_times))
    return [asset for asset in topo_order if asset in stale_assets]
