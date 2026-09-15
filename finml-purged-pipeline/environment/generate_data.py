#!/usr/bin/env python3
"""Generate synthetic financial ML dataset in DuckDB with opaque feature names."""
import json
import os

import duckdb
import numpy as np
import pandas as pd
from sklearn.datasets import make_classification



def main():
    np.random.seed(42)

    n_samples = 5000
    n_informative = 5
    n_redundant = 5
    n_noise = 10
    n_features = n_informative + n_redundant + n_noise

    X, y = make_classification(
        n_samples=n_samples,
        n_features=n_features,
        n_informative=n_informative,
        n_redundant=n_redundant,
        n_classes=2,
        random_state=42,
        shuffle=False,
        flip_y=0.01,
    )

    # Shuffle columns so opaque names do not reveal feature types
    perm = [14, 3, 8, 18, 1, 12, 7, 16, 0, 10, 5, 19, 9, 15, 2, 6, 17, 4, 11, 13]
    X = X[:, perm]

    dates = pd.bdate_range(end="2024-01-01", periods=n_samples)
    feature_names = [f"F_{i:02d}" for i in range(n_features)]

    # Overlapping label intervals: each spans 1-10 business days forward
    np.random.seed(42)
    spans = np.random.randint(1, 11, size=n_samples)
    t1_dates = []
    for i, s in enumerate(spans):
        end_idx = min(i + s, n_samples - 1)
        t1_dates.append(dates[end_idx])

    # Price series (random walk)
    np.random.seed(123)
    returns = np.random.normal(0.0001, 0.01, n_samples)
    prices = 100 * np.exp(np.cumsum(returns))

    os.makedirs("/app/data", exist_ok=True)

    # Store in DuckDB
    con = duckdb.connect("/app/data/market.duckdb")

    features_data = {"date": dates.strftime("%Y-%m-%d").tolist()}
    for i, name in enumerate(feature_names):
        features_data[name] = X[:, i].tolist()
    features_df = pd.DataFrame(features_data)
    con.execute("CREATE TABLE features AS SELECT * FROM features_df")

    labels_df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d").tolist(),
        "bin": y.astype(int).tolist(),
        "t1": pd.Series(t1_dates).dt.strftime("%Y-%m-%d").tolist(),
    })
    con.execute("CREATE TABLE labels AS SELECT * FROM labels_df")

    prices_df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d").tolist(),
        "close": prices.tolist(),
    })
    con.execute("CREATE TABLE prices AS SELECT * FROM prices_df")

    con.close()

    # Minimal metadata — NO feature type information
    metadata = {
        "n_samples": n_samples,
        "n_features": n_features,
        "feature_names": feature_names,
        "label_span_range": [1, 10],
        "db_path": "/app/data/market.duckdb",
        "tables": ["features", "labels", "prices"],
    }
    with open("/app/data/metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"Generated {n_samples} samples, {n_features} features in DuckDB")


if __name__ == "__main__":
    main()
