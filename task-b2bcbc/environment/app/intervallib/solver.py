"""Constraint propagation and resource load analysis over interval domains."""

from intervallib.intervals import overlaps, merge, coverage


def propagate_precedence(domains, precedences, max_rounds=100):
    """Propagate precedence constraints to narrow interval domains.

    Uses arc consistency to iteratively tighten variable domains based on
    precedence relationships.  A precedence (A, B) means A must complete
    before B starts in any valid assignment within their domains.

    Args:
        domains: dict mapping variable name -> (lo, hi) half-open interval
        precedences: list of (predecessor_name, successor_name) pairs
        max_rounds: maximum propagation iterations

    Returns:
        dict of narrowed domains, or None if infeasible (some domain becomes empty)
    """
    d = {k: list(v) for k, v in domains.items()}

    for _ in range(max_rounds):
        changed = False
        for pred, succ in precedences:
            dp = d[pred]
            ds = d[succ]

            if dp[1] > ds[1]:
                dp[1] = ds[1]
                changed = True

            if ds[0] < dp[0]:
                ds[0] = dp[0]
                changed = True

            if dp[0] >= dp[1] or ds[0] >= ds[1]:
                return None

        if not changed:
            break

    return {k: tuple(v) for k, v in d.items()}


def resource_load_profile(allocations, time_start, time_end, resolution):
    """Compute per-slot resource load across a time range.

    Discretizes the time range into slots of the given resolution and
    counts how many allocations overlap each slot.

    Args:
        allocations: list of (start, end) half-open intervals
        time_start: beginning of analysis window
        time_end: end of analysis window
        resolution: width of each time slot

    Returns:
        list of (slot_start, slot_end, load_count) tuples
    """
    if resolution <= 0 or time_start >= time_end:
        return []

    slots = []
    t = time_start
    while t < time_end:
        slot_end = min(t + resolution, time_end)
        load = sum(1 for a in allocations if overlaps(a, (t, slot_end)))
        slots.append((t, slot_end, load))
        t += resolution

    return slots


def find_overloaded_windows(allocations, time_start, time_end, capacity, resolution):
    """Find contiguous time windows where load exceeds capacity.

    Args:
        allocations: list of (start, end) half-open intervals
        time_start, time_end: analysis window
        capacity: maximum allowed concurrent allocations
        resolution: time slot width

    Returns:
        list of merged (start, end) windows where load > capacity
    """
    profile = resource_load_profile(allocations, time_start, time_end, resolution)
    overloaded = []
    for slot_start, slot_end, load in profile:
        if load > capacity:
            overloaded.append((slot_start, slot_end))

    return merge(overloaded)


def schedule_with_constraints(tasks, precedences, resource_capacity):
    """Schedule tasks respecting precedence constraints and resource limits.

    Uses a priority-based heuristic: tasks are scheduled in topological order
    (by number of predecessors), starting each task at the earliest feasible
    time that doesn't violate precedence or resource constraints.

    Args:
        tasks: list of (task_id, duration) tuples
        precedences: list of (predecessor_id, successor_id) pairs
        resource_capacity: max concurrent tasks

    Returns:
        dict mapping task_id -> (start, end), or None if infeasible
    """
    from collections import defaultdict

    successors = defaultdict(list)
    pred_count = {}
    task_durations = {}

    for task_id, duration in tasks:
        task_durations[task_id] = duration
        pred_count.setdefault(task_id, 0)

    for pred, succ in precedences:
        successors[pred].append(succ)
        pred_count[succ] = pred_count.get(succ, 0) + 1

    ready = sorted([tid for tid in task_durations if pred_count.get(tid, 0) == 0])
    schedule = {}
    active = []
    time = 0
    remaining = dict(pred_count)

    while ready or active:
        while (len(active) >= resource_capacity or not ready) and active:
            active.sort()
            end_time, completed = active.pop(0)
            time = max(time, end_time)
            for s in successors[completed]:
                remaining[s] -= 1
                if remaining[s] == 0:
                    ready.append(s)
            ready.sort()

        if not ready:
            break

        task_id = ready.pop(0)
        earliest = time
        for pred, succ in precedences:
            if succ == task_id and pred in schedule:
                earliest = max(earliest, schedule[pred][1])

        start = earliest
        end = start + task_durations[task_id]
        schedule[task_id] = (start, end)
        active.append((end, task_id))

    if len(schedule) != len(tasks):
        return None

    return schedule


def compute_makespan(schedule):
    """Return the makespan (latest end time) of a schedule."""
    if not schedule:
        return 0
    return max(end for _, end in schedule.values())
