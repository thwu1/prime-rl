# Output Schemas

Write the following JSON files to `/app/output/`.

## novelty_scores.json

```json
{
  "<benchmark>": {
    "<fuzzer>": {
      "novelty_score": <float, 4 decimal places>,
      "total_edges": <int>,
      "unique_edges": <int>,
      "rank": <float, 1 decimal place>
    }
  }
}
```

## aggregate_ranking.json

```json
[
  {
    "fuzzer": "<name>",
    "mean_rank": <float, 2 decimal places>,
    "total_novelty": <float, 4 decimal places>,
    "per_benchmark_ranks": {"<benchmark>": <float, 1 decimal place>}
  }
]
```

Sorted by ascending `mean_rank`, ties broken by descending `total_novelty`.

## statistical_tests.json

```json
{
  "<benchmark>": {
    "<fuzzer_i>_vs_<fuzzer_j>": {
      "u_statistic": <float>,
      "p_value": <float, 6 decimal places>,
      "p_value_corrected": <float, 6 decimal places>,
      "significant": <bool>
    }
  }
}
```

Fuzzer pairs ordered alphabetically: `fuzzer_i < fuzzer_j`.

## coverage_velocity.json

```json
{
  "<benchmark>": {
    "<fuzzer>": {
      "snapshots": [
        {"time": <int>, "mean_edges": <float, 2 decimal places>}
      ],
      "velocities": [
        {"interval": [<t1>, <t2>], "edges_per_second": <float, 4 decimal places>}
      ]
    }
  }
}
```
