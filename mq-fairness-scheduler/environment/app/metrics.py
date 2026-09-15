"""Fairness and throughput metrics for multi-queue simulation.

"""


def jains_fairness_index(throughputs, weights=None):
    """Compute Jain's fairness index, optionally with weight normalization.

    JFI = (sum(x_i))^2 / (n * sum(x_i^2))
    With weights: x_i = throughput_i / weight_i
    """
    if weights is None:
        weights = [1.0] * len(throughputs)

    normalized = [t / w for t, w in zip(throughputs, weights) if w > 0]
    n = len(normalized)
    if n == 0:
        return 1.0

    sum_x = sum(normalized)
    sum_x2 = sum(x * x for x in normalized)

    if sum_x2 == 0:
        return 1.0

    return (sum_x ** 2) / (n * sum_x2)


def compute_throughputs(send_log, duration_sec):
    """Compute per-flow average throughput from send log.

    Args:
        send_log: list of (time, flow_id, bytes_sent)
        duration_sec: total simulation duration

    Returns: dict of flow_id -> average throughput in bytes/sec
    """
    totals = {}
    for _, flow_id, bytes_sent in send_log:
        totals[flow_id] = totals.get(flow_id, 0) + bytes_sent

    return {fid: total / duration_sec for fid, total in totals.items()}
