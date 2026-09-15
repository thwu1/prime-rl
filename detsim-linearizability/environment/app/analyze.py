"""
Analysis pipeline for simulation histories.

Reads all history JSON files from /app/histories/,
runs the linearizability checker on each,
and writes results to /app/results.json.

Output format (results.json):
{
  "seed_001": {"linearizable": true},
  "seed_002": {"linearizable": false},
  ...
}
"""


def main():
    raise NotImplementedError("Implement the analysis pipeline")


if __name__ == "__main__":
    main()
