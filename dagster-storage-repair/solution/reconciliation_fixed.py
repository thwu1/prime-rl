"""
Fixed asset reconciliation module.

Bugs fixed:
1. topological_sort — nodes appearing only as values (not keys) in asset_deps
   are now included in the in-degree map so they appear in the output.
2. get_weekly_partition_for_daily — uses weekday() (Mon=0) instead of
   isoweekday() (Mon=1) to correctly compute the Monday of the week.
3. find_stale_assets — uses any() instead of all() so an asset is marked stale
   when ANY upstream is newer, not only when ALL are.
4. compute_reconciliation_plan — propagates staleness transitively through the
   dependency graph so that downstream assets of stale upstreams are also
   included in the plan.
5. validate_partition_completeness — uses range(7) instead of range(6) to
   check all 7 days (Monday through Sunday) of a weekly partition.

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
    """
    in_degree = {}
    graph = defaultdict(list)

    for asset, deps in asset_deps.items():
        if asset not in in_degree:
            in_degree[asset] = 0
        in_degree[asset] = len(deps)
        for dep in deps:
            graph[dep].append(asset)
            # FIX: ensure deps that only appear as values get an entry
            if dep not in in_degree:
                in_degree[dep] = 0

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
    """
    date = datetime.strptime(daily_partition_key, "%Y-%m-%d")
    # FIX: weekday() returns 0 for Monday (correct), not isoweekday() which
    # returns 1 for Monday and would shift every day back by one.
    monday = date - timedelta(days=date.weekday())
    return monday.strftime("%Y-%m-%d")


def get_daily_partitions_for_weekly(weekly_partition_key):
    """Given a weekly partition key (Monday), return all 7 daily partition keys."""
    monday = datetime.strptime(weekly_partition_key, "%Y-%m-%d")
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def find_stale_assets(asset_deps, materialization_times):
    """
    Find assets that need re-materialization because at least one upstream
    dependency has been materialized more recently.
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

        # FIX: any() — stale if ANY upstream is newer, not all()
        if any(ts > downstream_ts for ts in upstream_timestamps):
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
    # FIX: range(7) to include all 7 days (Monday through Sunday),
    # not range(6) which would miss Sunday
    expected = set(
        (monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)
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

    # FIX: propagate transitive staleness through the dependency graph.
    # If any upstream dep is stale, the downstream asset is also stale
    # regardless of its own timestamp comparisons.
    for asset in topo_order:
        deps = asset_deps.get(asset, [])
        if any(dep in stale_assets for dep in deps):
            stale_assets.add(asset)

    return [asset for asset in topo_order if asset in stale_assets]
