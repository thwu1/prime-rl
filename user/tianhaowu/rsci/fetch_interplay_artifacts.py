#!/usr/bin/env python
"""Download the exact released artifacts needed for the Figure 3 reproduction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_REPO = "Interplay-LM-Reasoning/extrapolation_rl"
DATA_REPO = "Interplay-LM-Reasoning/composition"
MODEL_REVISION = "4861bd030e6fb92d94be3a1cecab89c2fac4b94a"
DATA_REVISION = "a09d5c14c02bfa339143fb00a93274d1a84aa31d"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True, help="Hugging Face hub cache directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        cache_dir=args.cache_dir,
        allow_patterns=[
            "README.md",
            "id2-10_0.2easy_0.3medium_0.5hard/base/*",
            "id2-10_0.2easy_0.3medium_0.5hard/rl/op11-14_uniform/*",
        ],
    )
    data_path = snapshot_download(
        repo_id=DATA_REPO,
        revision=DATA_REVISION,
        repo_type="dataset",
        cache_dir=args.cache_dir,
        allow_patterns=[
            "README.md",
            "val/*",
            "heldout/op11-50k.jsonl",
            "heldout/op12-50k.jsonl",
            "heldout/op13-50k.jsonl",
            "heldout/op14-50k.jsonl",
        ],
    )
    print(
        json.dumps(
            {
                "model_revision": MODEL_REVISION,
                "model_snapshot": model_path,
                "dataset_revision": DATA_REVISION,
                "dataset_snapshot": data_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
