"""Report generation and anomaly detection for latency metrics."""


def detect_anomalies(window_p99s, threshold):
    """Detect anomalous windows based on p99 latency changes.

    Compares consecutive windows and flags those with significant changes.

    Args:
        window_p99s: dict mapping window_id (int) to p99 value (float)
        threshold: change threshold for anomaly detection

    Returns:
        List of anomaly dicts with window_id, quantile, previous_value,
        current_value, and relative_change.
    """
    anomalies = []
    sorted_windows = sorted(window_p99s.keys())
    for i in range(1, len(sorted_windows)):
        wid = sorted_windows[i]
        prev_wid = sorted_windows[i - 1]
        current = window_p99s[wid]
        previous = window_p99s[prev_wid]
        change = abs(current - previous)
        if change > threshold:
            anomalies.append({
                "window_id": wid,
                "quantile": "0.99",
                "previous_value": previous,
                "current_value": current,
                "relative_change": round(change, 4)
            })
    return anomalies
