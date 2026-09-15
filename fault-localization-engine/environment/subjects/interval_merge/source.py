def merge_intervals(intervals):
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged = [list(sorted_ivs[0])]
    for current in sorted_ivs[1:]:
        last = merged[-1]
        if current[0] < last[1]:
            last[1] = max(last[1], current[1])
        else:
            merged.append(list(current))
    return [tuple(iv) for iv in merged]
