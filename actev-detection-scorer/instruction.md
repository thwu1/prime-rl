Implement a temporal activity detection evaluation scorer at `/app/scorer.py` that conforms to the evaluation protocol specified in `/app/protocol.md`.

The task environment provides:
- `/app/eval_data.db` — SQLite database with multi-annotator reference annotations and video metadata
- `/app/detections.jsonl` — system detection outputs
- `/app/eval_config.toml` — evaluation parameters and data paths
- `/app/protocol.md` — complete evaluation protocol specification

The scorer must produce all output files defined by the protocol:

```
python3 /app/scorer.py --config /app/eval_config.toml --output-dir /app/output
```