"""Scheduling algorithms using interval-based reasoning."""

from collections import defaultdict, deque


def weighted_schedule(jobs):
    """Find maximum weight subset of non-overlapping jobs.

    Args:
        jobs: list of (start, end, weight) tuples representing half-open intervals

    Returns:
        (max_weight, sorted list of original indices of selected jobs)
    """
    if not jobs:
        return (0, [])
    n = len(jobs)
    indexed = sorted(enumerate(jobs), key=lambda x: x[1][1])

    def latest_non_conflict(idx):
        target_start = indexed[idx][1][0]
        lo, hi = 0, idx - 1
        result = -1
        while lo <= hi:
            mid = (lo + hi) // 2
            if indexed[mid][1][1] <= target_start:
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return result

    dp = [0] * n
    dp[0] = indexed[0][1][2]
    take = [False] * n
    take[0] = True
    parent = [-1] * n

    for i in range(1, n):
        excl = dp[i - 1]
        incl = indexed[i][1][2]
        p = latest_non_conflict(i)
        if p != -1:
            incl += dp[p]
        if incl > excl:
            dp[i] = incl
            take[i] = True
            parent[i] = p
        else:
            dp[i] = excl
            take[i] = False

    selected = []
    i = n - 1
    while i >= 0:
        if take[i]:
            selected.append(indexed[i][0])
            i = parent[i]
        else:
            i -= 1
    return (dp[-1], sorted(selected))


def edf_schedule(tasks):
    """Schedule tasks using Earliest Deadline First policy.

    Args:
        tasks: list of (task_id, processing_time, deadline) tuples

    Returns:
        (ordered list of task_ids, maximum lateness)
    """
    sorted_tasks = sorted(tasks, key=lambda t: t[2])
    time = 0
    max_lateness = float('-inf')
    order = []
    for task_id, proc_time, deadline in sorted_tasks:
        time += proc_time
        lateness = time - deadline
        if lateness > max_lateness:
            max_lateness = lateness
        order.append(task_id)
    return (order, max_lateness)


def critical_path_length(n_tasks, durations, dependencies):
    """Find the critical path length (minimum project completion time) in a task DAG.

    Args:
        n_tasks: number of tasks (indexed 0 to n-1)
        durations: list of task durations
        dependencies: list of (predecessor, successor) pairs

    Returns:
        Earliest time all tasks can complete
    """
    adj = defaultdict(list)
    in_degree = [0] * n_tasks
    for u, v in dependencies:
        adj[u].append(v)
        in_degree[v] += 1
    earliest_start = [0] * n_tasks
    queue = deque()
    for i in range(n_tasks):
        if in_degree[i] == 0:
            queue.append(i)
    topo_order = []
    while queue:
        u = queue.popleft()
        topo_order.append(u)
        for v in adj[u]:
            es = earliest_start[u] + durations[u]
            if es > earliest_start[v]:
                earliest_start[v] = es
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
    if len(topo_order) != n_tasks:
        raise ValueError("Cycle detected in task dependencies")
    return max(earliest_start[i] + durations[i] for i in range(n_tasks))
