# Output Schema for `/app/output.json`

The output must be a JSON object with the following top-level keys:

```json
{
  "disagreement_removals": {
    "<division_name>": ["<benchmark_id>", ...]
  },
  "divisions": {
    "<division_name>": {
      "num_benchmarks": <int>,
      "parallel": {
        "<solver_name>": {
          "errors": <int>,
          "correct": <int>,
          "wallclock": <float>,
          "cpu": <float>
        }
      },
      "sequential": {
        "<solver_name>": {
          "errors": <int>,
          "correct": <int>,
          "cpu": <float>
        }
      },
      "par2": {
        "<solver_name>": {
          "wallclock": <float>,
          "cpu": <float>
        }
      },
      "parallel_ranking": ["<solver1>", "<solver2>", ...],
      "sequential_ranking": ["<solver1>", "<solver2>", ...]
    }
  },
  "derived_eligibility": {
    "<derived_solver>": {
      "<division_name>": {
        "eligible": <bool>,
        "improvement_pct": <float>
      },
      "competition_wide": <bool>
    }
  },
  "best_overall": {
    "parallel": {
      "scores": {"<solver>": <float>, ...},
      "ranking": ["<solver1>", "<solver2>", ...]
    },
    "sequential": {
      "scores": {"<solver>": <float>, ...},
      "ranking": ["<solver1>", "<solver2>", ...]
    }
  },
  "biggest_lead": {
    "parallel": {
      "divisions": {
        "<division_name>": {
          "winner": "<solver>",
          "correctness_rank": <float>,
          "wallclock_rank": <float>
        }
      },
      "overall_winner": "<solver>",
      "overall_division": "<division_name>"
    },
    "sequential": {
      "divisions": {
        "<division_name>": {
          "winner": "<solver>",
          "correctness_rank": <float>,
          "cpu_rank": <float>
        }
      },
      "overall_winner": "<solver>",
      "overall_division": "<division_name>"
    }
  },
  "largest_contribution": {
    "parallel": {
      "divisions": {
        "<division_name>": {
          "<solver>": {
            "correctness_rank": <float>,
            "wallclock_rank": <float>,
            "normalized_correctness": <float>,
            "normalized_wallclock": <float>
          }
        }
      },
      "overall_winner": "<solver>",
      "overall_division": "<division_name>"
    },
    "sequential": {
      "divisions": {
        "<division_name>": {
          "<solver>": {
            "correctness_rank": <float>,
            "cpu_rank": <float>,
            "normalized_correctness": <float>,
            "normalized_cpu": <float>
          }
        }
      },
      "overall_winner": "<solver>",
      "overall_division": "<division_name>"
    }
  }
}
```

## Notes

- All float values should be rounded to 6 decimal places.
- Division keys must match exactly the division names from the input data.
- Solver keys must match exactly the solver names from the input data.
- Rankings are lists sorted from best (index 0) to worst.
- `disagreement_removals`: list of removed benchmark IDs per division. Empty list `[]` if no benchmarks were removed.
- `num_benchmarks`: number of benchmarks used for scoring AFTER disagreement removal.
- `parallel_ranking` / `sequential_ranking`: all solvers that entered the division, sorted best to worst.
- `par2.wallclock` and `par2.cpu`: the PAR-2 score summed across all benchmarks in the division.
- `improvement_pct`: the improvement percentage as `(base - derived) / base * 100`.
- For `largest_contribution`, only include divisions with > 2 competitive sound solvers.
- For `best_overall`, only include solvers in divisions they entered. The overall score sums contributions from entered competitive divisions only.
