"""Loghub-2.0 evaluation metrics: GA, FGA, PA, FTA."""

import pandas as pd


def compute_ga_fga(gt_series, parsed_series):
    """Compute Grouping Accuracy (GA) and its F-measure (FGA).

    Parameters
    ----------
    gt_series : pd.Series   — ground truth template strings
    parsed_series : pd.Series — parsed template strings (row-aligned)

    Returns
    -------
    (GA, FGA) : tuple of float
    """
    df = pd.DataFrame({
        "groundtruth": gt_series.values,
        "parsedlog": parsed_series.values,
    })
    df = df[df["groundtruth"].notna()].reset_index(drop=True)
    n = len(df)
    if n == 0:
        return 0.0, 0.0

    parsed_counts = df["parsedlog"].value_counts()
    grouped = df.groupby("groundtruth")

    accurate_events = 0
    accurate_templates = 0

    for _gt_tmpl, group in grouped:
        parsed_in_group = group["parsedlog"].value_counts()
        if len(parsed_in_group) == 1:
            p_star = parsed_in_group.index[0]
            if len(group) == parsed_counts[p_star]:
                accurate_events += len(group)
                accurate_templates += 1

    GA = accurate_events / n

    m = len(parsed_counts)
    k = len(grouped)

    PGA = accurate_templates / m if m > 0 else 0.0
    RGA = accurate_templates / k if k > 0 else 0.0
    FGA = 2 * PGA * RGA / (PGA + RGA) if (PGA + RGA) > 0 else 0.0

    return GA, FGA


def compute_pa(gt_series, parsed_series):
    """Compute Parsing Accuracy (PA) — exact string match per message."""
    df = pd.DataFrame({
        "groundtruth": gt_series.values,
        "parsedlog": parsed_series.values,
    })
    df = df[df["groundtruth"].notna()].reset_index(drop=True)
    n = len(df)
    if n == 0:
        return 0.0
    correct = (df["groundtruth"] == df["parsedlog"]).sum()
    return float(correct) / n


def compute_fta(gt_series, parsed_series):
    """Compute F-measure of Template Accuracy (FTA).

    Groups by *parsed* template and checks whether each parsed group
    maps to exactly one GT template with matching text.
    """
    df = pd.DataFrame({
        "groundtruth": gt_series.values,
        "parsedlog": parsed_series.values,
    })
    df = df[df["groundtruth"].notna()].reset_index(drop=True)
    if len(df) == 0:
        return 0.0

    grouped_by_parsed = df.groupby("parsedlog")
    k = df["groundtruth"].nunique()

    correct = 0
    for parsed_template, group in grouped_by_parsed:
        oracle_set = set(group["groundtruth"])
        if oracle_set == {parsed_template}:
            correct += 1

    m = len(grouped_by_parsed)
    PTA = correct / m if m > 0 else 0.0
    RTA = correct / k if k > 0 else 0.0
    FTA = 2 * PTA * RTA / (PTA + RTA) if (PTA + RTA) > 0 else 0.0
    return FTA
