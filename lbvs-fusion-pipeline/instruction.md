A molecular activity dataset and experimental configuration for a drug target are located in `/app/`. Explore the environment to understand the available data, configuration, installed libraries, and any existing analysis work.

Your objective is to produce a correct and comprehensive fingerprint-based virtual screening benchmarking analysis. The analysis must properly handle molecular data quality issues, use evaluation methodology appropriate for the virtual screening domain, and benchmark multiple individual fingerprint approaches alongside score-level fusion strategies.

Write your results to `/app/results.json` conforming to this schema:

```json
{
  "config_used": { "<verbatim copy of the experimental configuration>" },
  "preprocessing": {
    "n_molecules_raw": "<int>",
    "n_molecules_valid": "<int>",
    "n_molecules_after_pains": "<int>",
    "n_actives_after_pains": "<int>",
    "n_inactives_after_pains": "<int>"
  },
  "per_split_results": [
    {
      "seed": "<int>",
      "n_train": "<int>",
      "n_test": "<int>",
      "n_train_actives": "<int>",
      "methods": {
        "ecfp_binary": {"bedroc": "<float>", "ef": "<float>"},
        "ecfp_count": {"bedroc": "<float>", "ef": "<float>"},
        "atom_pair": {"bedroc": "<float>", "ef": "<float>"},
        "maccs": {"bedroc": "<float>", "ef": "<float>"},
        "combsum_fusion": {"bedroc": "<float>", "ef": "<float>"},
        "rank_fusion": {"bedroc": "<float>", "ef": "<float>"}
      }
    }
  ],
  "summary": {
    "<method_name>": {
      "bedroc_mean": "<float>", "bedroc_std": "<float>",
      "ef_mean": "<float>", "ef_std": "<float>"
    },
    "best_method_bedroc": "<method name with highest mean BEDROC>",
    "best_method_ef": "<method name with highest mean EF>"
  }
}
```

Method keys must be exactly: `ecfp_binary`, `ecfp_count`, `atom_pair`, `maccs`, `combsum_fusion`, `rank_fusion`.