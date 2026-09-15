#!/usr/bin/env python3
"""
Reference solution: financial feature classification pipeline.

Reads from DuckDB, implements overlap-aware sampling, leakage-free evaluation,
return-attribution weights, multi-method feature importance, and consensus
classification. Writes results to JSON and intermediate analysis to SQLite.

"""
import json
import os
import sqlite3

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection._split import _BaseKFold


# ================================================================
# Indicator matrix & average uniqueness
# ================================================================

def get_ind_matrix(bar_ix, t1):
    """Binary indicator: indM[bar, label] = 1 if label is active at bar."""
    ind_m = pd.DataFrame(0, index=bar_ix, columns=range(t1.shape[0]))
    for i, (t0, t1_val) in enumerate(t1.items()):
        ind_m.loc[t0:t1_val, i] = 1.0
    return ind_m


def get_avg_uniqueness(ind_m):
    """Average uniqueness per label given the indicator matrix."""
    c = ind_m.sum(axis=1)
    c[c == 0] = 1
    u = ind_m.div(c, axis=0)
    return u[u > 0].mean()


# ================================================================
# Overlap-aware sampling
# ================================================================

def seq_bootstrap(ind_m, s_length=None, random_state=42):
    """Draw samples preferring temporally independent observations."""
    rng = np.random.RandomState(random_state)
    if s_length is None:
        s_length = ind_m.shape[1]
    phi = []
    while len(phi) < s_length:
        avg_u = pd.Series(dtype=float)
        for i in ind_m.columns:
            ind_m_ = ind_m[phi + [i]]
            avg_u.loc[i] = get_avg_uniqueness(ind_m_).iloc[-1]
        prob = avg_u / avg_u.sum()
        phi.append(rng.choice(ind_m.columns, p=prob.values))
    return phi


# ================================================================
# Concurrent events & sample weights
# ================================================================

def num_co_events(close_idx, t1):
    """Count concurrent labels at each bar."""
    t1_ = t1.fillna(close_idx[-1])
    i_lo = close_idx.searchsorted(t1_.index[0])
    i_hi = close_idx.searchsorted(t1_.max())
    count = pd.Series(0.0, index=close_idx[i_lo:i_hi + 1])
    for t_in, t_out in t1_.items():
        count.loc[t_in:t_out] += 1.0
    return count


def sample_tw(t1, num_co):
    """Average-uniqueness sample weight (1 / concurrency)."""
    w = pd.Series(index=t1.index, dtype=float)
    for t_in, t_out in t1.items():
        w.loc[t_in] = (1.0 / num_co.loc[t_in:t_out]).mean()
    return w


def sample_w(t1, num_co, close):
    """Return-attribution sample weight."""
    ret = np.log(close).diff()
    w = pd.Series(index=t1.index, dtype=float)
    for t_in, t_out in t1.items():
        co = num_co.loc[t_in:t_out]
        r = ret.loc[t_in:t_out]
        common = co.index.intersection(r.index)
        w.loc[t_in] = (r.loc[common] / co.loc[common]).sum() if len(common) else 0.0
    return w.abs()


# ================================================================
# Leakage-free cross-validation
# ================================================================

class PurgedKFold(_BaseKFold):
    """K-Fold that excludes overlapping labels + buffer."""

    def __init__(self, n_splits=3, t1=None, pct_embargo=0.0):
        if not isinstance(t1, pd.Series):
            raise ValueError("t1 must be a pd.Series")
        super().__init__(n_splits=n_splits, shuffle=False, random_state=None)
        self.t1 = t1
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, groups=None):
        if (X.index == self.t1.index).sum() != len(self.t1):
            raise ValueError("X and t1 must share the same index")
        indices = np.arange(X.shape[0])
        mbrg = int(X.shape[0] * self.pct_embargo)
        test_ranges = [
            (chunk[0], chunk[-1] + 1)
            for chunk in np.array_split(indices, self.n_splits)
        ]
        for i, j in test_ranges:
            t0 = self.t1.index[i]
            test_idx = indices[i:j]
            max_t1_idx = self.t1.index.searchsorted(
                self.t1.iloc[test_idx].max()
            )
            left = self.t1.index.searchsorted(self.t1[self.t1 <= t0].index)
            if max_t1_idx < X.shape[0]:
                right = indices[max_t1_idx + mbrg:]
                train_idx = np.concatenate((left, right))
            else:
                train_idx = left
            yield train_idx, test_idx


def cv_score(clf, X, y, t1, n_splits=5, pct_embargo=0.02):
    """Leakage-free CV scores, exclusion counts, and fold assignments."""
    cv_gen = PurgedKFold(n_splits=n_splits, t1=t1, pct_embargo=pct_embargo)
    scores, n_excluded, cv_records = [], [], []
    dates_str = [d.strftime("%Y-%m-%d") for d in X.index]

    for fold_idx, (train, test) in enumerate(cv_gen.split(X)):
        c = clf.__class__(**clf.get_params())
        c.fit(X.iloc[train], y.iloc[train])
        pred = c.predict(X.iloc[test])
        scores.append(accuracy_score(y.iloc[test], pred))

        all_set = set(range(X.shape[0]))
        train_set = set(train.tolist())
        test_set = set(test.tolist())
        excl_set = all_set - train_set - test_set
        n_excluded.append(len(excl_set))

        for idx in train:
            cv_records.append({
                "fold": fold_idx, "date": dates_str[idx], "role": "train"
            })
        for idx in test:
            cv_records.append({
                "fold": fold_idx, "date": dates_str[idx], "role": "test"
            })
        for idx in sorted(excl_set):
            cv_records.append({
                "fold": fold_idx, "date": dates_str[idx], "role": "excluded"
            })

    return scores, n_excluded, cv_records


# ================================================================
# Feature importance methods
# ================================================================

def feat_imp_mdi(clf, feat_names):
    """Impurity-based importance from a fitted random forest."""
    imp = {i: tree.feature_importances_ for i, tree in enumerate(clf.estimators_)}
    df = pd.DataFrame.from_dict(imp, orient="index")
    df.columns = feat_names
    out = pd.concat(
        {"mean": df.mean(), "std": df.std() * df.shape[0] ** -0.5}, axis=1
    )
    out /= out["mean"].sum()
    return out


def feat_imp_mda(clf, X, y, t1, n_splits=5, pct_embargo=0.02):
    """Permutation-based importance under leakage-free CV."""
    cv_gen = PurgedKFold(n_splits=n_splits, t1=t1, pct_embargo=pct_embargo)
    base_scores = pd.Series(dtype=float)
    perm_scores = pd.DataFrame(columns=X.columns)

    for fold, (train, test) in enumerate(cv_gen.split(X)):
        c = clf.__class__(**clf.get_params())
        c.fit(X.iloc[train], y.iloc[train])
        X_test = X.iloc[test]
        y_test = y.iloc[test]
        base_scores.loc[fold] = accuracy_score(y_test, c.predict(X_test))
        for col in X.columns:
            X_perm = X_test.copy()
            np.random.RandomState(42 + fold).shuffle(X_perm[col].values)
            perm_scores.loc[fold, col] = accuracy_score(
                y_test, c.predict(X_perm)
            )

    delta = (-perm_scores.astype(float)).add(base_scores, axis=0)
    return pd.concat(
        {"mean": delta.mean(), "std": delta.std() * delta.shape[0] ** -0.5},
        axis=1,
    )


def feat_imp_sfi(clf, X, y, t1, n_splits=5, pct_embargo=0.02):
    """Single-feature importance under leakage-free CV."""
    imp = pd.DataFrame(columns=["mean", "std"])
    for feat in X.columns:
        cv_gen = PurgedKFold(n_splits=n_splits, t1=t1, pct_embargo=pct_embargo)
        scores = pd.Series(dtype=float)
        for fold, (train, test) in enumerate(cv_gen.split(X)):
            c = clf.__class__(**clf.get_params())
            c.fit(X[[feat]].iloc[train], y.iloc[train])
            pred = c.predict(X[[feat]].iloc[test])
            scores.loc[fold] = accuracy_score(y.iloc[test], pred)
        imp.loc[feat] = [scores.mean(), scores.std() * scores.shape[0] ** -0.5]
    return imp


# ================================================================
# Main pipeline
# ================================================================

def main():
    # ── Load data from DuckDB ──
    print("Loading data from DuckDB …")
    con = duckdb.connect("/app/data/market.duckdb", read_only=True)

    X = con.execute("SELECT * FROM features ORDER BY date").fetchdf()
    X = X.set_index("date")
    X.index = pd.to_datetime(X.index)

    labels = con.execute("SELECT * FROM labels ORDER BY date").fetchdf()
    labels = labels.set_index("date")
    labels.index = pd.to_datetime(labels.index)
    labels["t1"] = pd.to_datetime(labels["t1"])

    prices = con.execute("SELECT * FROM prices ORDER BY date").fetchdf()
    prices = prices.set_index("date")
    prices.index = pd.to_datetime(prices.index)

    con.close()

    y = labels["bin"]
    t1 = labels["t1"]
    close = prices["close"]
    results = {}
    dates_str = [d.strftime("%Y-%m-%d") for d in X.index]

    # ── Sampling analysis ──
    print("Sampling analysis …")
    pool_n = 100
    draw_n = 20
    t1_sub = t1.iloc[:pool_n]
    last_bar = close.index.searchsorted(t1_sub.max())
    bar_ix = close.index[:last_bar + 1]
    ind_m = get_ind_matrix(bar_ix, t1_sub)

    phi_seq = seq_bootstrap(ind_m, s_length=draw_n, random_state=42)
    avg_u_seq = float(get_avg_uniqueness(ind_m[phi_seq]).mean())

    random_us = []
    for seed in range(10):
        rng = np.random.RandomState(seed)
        phi_rand = list(rng.choice(ind_m.columns, size=draw_n))
        random_us.append(float(get_avg_uniqueness(ind_m[phi_rand]).mean()))
    avg_u_rand = float(np.mean(random_us))

    results["sampling_analysis"] = {
        "avg_uniqueness_corrected": avg_u_seq,
        "avg_uniqueness_random": avg_u_rand,
    }
    print(f"  corrected={avg_u_seq:.4f}  random={avg_u_rand:.4f}")

    # ── Sample weights ──
    print("Sample weights …")
    num_co = num_co_events(close.index, t1)
    num_co = num_co.loc[~num_co.index.duplicated(keep="last")]
    num_co = num_co.reindex(close.index).fillna(0)

    tw = sample_tw(t1, num_co)
    sw = sample_w(t1, num_co, close)
    sw *= sw.shape[0] / sw.sum()

    results["sample_weights"] = {
        "mean_uniqueness": float(tw.mean()),
        "mean_weight": float(sw.mean()),
        "std_weight": float(sw.std()),
        "n_samples": int(sw.shape[0]),
    }

    # ── Evaluation ──
    print("Evaluation …")
    clf_cv = RandomForestClassifier(
        n_estimators=100, max_depth=5, criterion="entropy",
        class_weight="balanced_subsample", random_state=42, n_jobs=1,
    )
    n_splits, pct_embargo = 5, 0.02
    scores, n_excluded, cv_records = cv_score(
        clf_cv, X, y, t1, n_splits=n_splits, pct_embargo=pct_embargo
    )
    results["evaluation"] = {
        "mean_score": float(np.mean(scores)),
        "std_score": float(np.std(scores)),
        "scores": [float(s) for s in scores],
        "n_splits": n_splits,
        "pct_embargo": pct_embargo,
        "n_excluded_per_fold": [int(n) for n in n_excluded],
    }
    print(f"  mean accuracy={np.mean(scores):.4f}")

    # ── Feature importance: impurity-based ──
    print("Feature importance (impurity) …")
    clf_mdi = RandomForestClassifier(
        n_estimators=200, max_depth=5, criterion="entropy",
        class_weight="balanced_subsample", random_state=42, n_jobs=1,
    )
    clf_mdi.fit(X, y)
    mdi = feat_imp_mdi(clf_mdi, X.columns)
    mdi_ranked = mdi.sort_values("mean", ascending=False)

    # ── Feature importance: permutation-based ──
    print("Feature importance (permutation) …")
    clf_mda = RandomForestClassifier(
        n_estimators=100, max_depth=5, criterion="entropy",
        class_weight="balanced_subsample", random_state=42, n_jobs=1,
    )
    mda = feat_imp_mda(clf_mda, X, y, t1, n_splits=5, pct_embargo=0.02)
    mda_ranked = mda.sort_values("mean", ascending=False)

    # ── Feature importance: single-feature ──
    print("Feature importance (single-feature) …")
    clf_sfi = RandomForestClassifier(
        n_estimators=50, max_depth=3, criterion="entropy",
        class_weight="balanced_subsample", random_state=42, n_jobs=1,
    )
    sfi = feat_imp_sfi(clf_sfi, X, y, t1, n_splits=5, pct_embargo=0.02)
    sfi_ranked = sfi.sort_values("mean", ascending=False)

    method_names = [
        "impurity_decrease", "permutation_accuracy", "single_feature"
    ]
    results["feature_importance"] = {
        "rankings": {
            method_names[0]: list(mdi_ranked.index),
            method_names[1]: list(mda_ranked.index),
            method_names[2]: list(sfi_ranked.index),
        }
    }

    # ── Feature classification by consensus ──
    mdi_top10 = set(mdi_ranked.index[:10])
    mda_top10 = set(mda_ranked.index[:10])
    sfi_top10 = set(sfi_ranked.index[:10])
    mda_top5 = set(mda_ranked.index[:5])

    fc = {}
    for feat in X.columns:
        cnt = sum(feat in s for s in (mdi_top10, mda_top10, sfi_top10))
        if cnt >= 2:
            if feat in mda_top5:
                fc[feat] = "informative"
            else:
                fc[feat] = "redundant"
        elif cnt == 1 and feat in mda_top5:
            fc[feat] = "informative"
        else:
            fc[feat] = "noise"
    results["feature_classification"] = fc

    # ── Write JSON results ──
    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # ── Write SQLite analysis database ──
    print("Writing analysis database …")
    sqlite_con = sqlite3.connect("/app/results/analysis.db")

    sw_df = pd.DataFrame({
        "date": dates_str,
        "weight": sw.values,
        "uniqueness": tw.values,
    })
    sw_df.to_sql("sample_weights", sqlite_con, index=False, if_exists="replace")

    cv_df = pd.DataFrame(cv_records)
    cv_df.to_sql("cv_assignments", sqlite_con, index=False, if_exists="replace")

    fs_records = []
    for method_name, imp_df in [
        (method_names[0], mdi),
        (method_names[1], mda),
        (method_names[2], sfi),
    ]:
        for feat, row in imp_df.iterrows():
            fs_records.append({
                "feature": feat,
                "method": method_name,
                "score": float(row["mean"]),
            })
    fs_df = pd.DataFrame(fs_records)
    fs_df.to_sql("feature_scores", sqlite_con, index=False, if_exists="replace")

    sqlite_con.close()

    print("\nDone. Results → /app/results/results.json + /app/results/analysis.db")


if __name__ == "__main__":
    main()
