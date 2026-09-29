"""Convert a prime-rl DCP trainer checkpoint of a NemotronH model into an HF safetensors directory.

The trainer's HF weight save gathers the whole model on rank 0, which does not fit in host RAM
next to FSDP CPU-offloaded training state on a 900 GB GB300 node. This converter runs offline on
a single process and streams one decoder layer at a time: it loads only that layer's model keys
from the DCP checkpoint (resharded to full tensors), converts them to the HF layout with the same
`convert_prime_layer_to_hf` the trainer uses, casts to bf16 and writes one safetensors shard.
Peak memory is about one layer plus the embeddings.

Config, generation config, remote-code files and tokenizer are copied from the base model dir.
"""

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import torch
import torch.distributed.checkpoint as dcp
from safetensors import safe_open
from safetensors.torch import save_file
from torch.distributed.checkpoint import FileSystemReader
from torch.distributed.checkpoint.metadata import TensorStorageMetadata
from transformers import AutoConfig

from prime_rl.trainer.models.nemotron_h.converting_nemotron_h import convert_prime_layer_to_hf

MODEL_PREFIX = "app.model."
LAYER_KEY = re.compile(r"^model\.layers\.(\d+)\.")
BASE_FILES = ("*.json", "*.py", "*.jinja", "*.model", "*.tiktoken", "*.txt")


def to_hf_names(state_dict: dict[str, torch.Tensor], layer_idx: int | None, layer_type: str | None) -> dict:
    if layer_idx is not None:
        convert_prime_layer_to_hf(state_dict, layer_idx, layer_type)
    renames = {"model.embed_tokens.weight": "model.embeddings.weight", "model.norm.weight": "model.norm_f.weight"}
    out = {}
    for key, value in state_dict.items():
        key = renames.get(key, key)
        if key.startswith("model."):
            key = "backbone." + key[len("model.") :]
        out[key] = value
    return out


def base_dtypes(base_model: Path) -> dict[str, torch.dtype]:
    """Per-tensor dtypes of the base checkpoint (e.g. fp32 router correction biases)."""
    index = json.loads((base_model / "model.safetensors.index.json").read_text())["weight_map"]
    dtypes: dict[str, torch.dtype] = {}
    for shard in sorted(set(index.values())):
        with safe_open(base_model / shard, "pt") as handle:
            for key in handle.keys():
                dtypes[key] = handle.get_slice(key).get_dtype()
    return {key: getattr(torch, {"F32": "float32", "BF16": "bfloat16", "F16": "float16"}[value]) if isinstance(value, str) else value
            for key, value in dtypes.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dcp-dir", type=Path, required=True, help=".../checkpoints/step_N/trainer")
    parser.add_argument("--base-model", type=Path, required=True, help="HF dir providing config/tokenizer")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dtype", default="bfloat16", help="dtype for tensors absent from the base checkpoint")
    args = parser.parse_args()

    dtype = getattr(torch, args.dtype)
    config = AutoConfig.from_pretrained(args.base_model, trust_remote_code=True)
    target_dtypes = base_dtypes(args.base_model)
    reader = FileSystemReader(args.dcp_dir)
    metadata = reader.read_metadata()
    model_keys = {
        key[len(MODEL_PREFIX) :]: meta
        for key, meta in metadata.state_dict_metadata.items()
        if key.startswith(MODEL_PREFIX) and isinstance(meta, TensorStorageMetadata)
    }
    if not model_keys:
        raise SystemExit(f"no {MODEL_PREFIX}* tensors in {args.dcp_dir}")

    groups: dict[int | None, list[str]] = defaultdict(list)
    for key in model_keys:
        match = LAYER_KEY.match(key)
        groups[int(match.group(1)) if match else None].append(key)
    layer_types = list(config.layers_block_type)
    layer_indices = sorted(i for i in groups if i is not None)
    if layer_indices != list(range(len(layer_types))):
        raise SystemExit(f"checkpoint layers {layer_indices[:3]}..{layer_indices[-3:]} do not match config ({len(layer_types)})")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    order = [None, *layer_indices]
    weight_map: dict[str, str] = {}
    total_bytes = 0
    for shard_idx, group in enumerate(order):
        keys = groups[group]
        template = {key: torch.empty(model_keys[key].size, dtype=model_keys[key].properties.dtype) for key in keys}
        dcp.load({"app": {"model": template}}, storage_reader=reader, no_dist=True)
        state_dict = dict(template)
        del template
        hf = to_hf_names(state_dict, group, None if group is None else layer_types[group])
        hf = {key: value.to(target_dtypes.get(key, dtype)).contiguous() for key, value in hf.items()}
        shard_name = f"model-{shard_idx + 1:05d}-of-{len(order):05d}.safetensors"
        save_file(hf, args.output_dir / shard_name, metadata={"format": "pt"})
        for key, value in hf.items():
            weight_map[key] = shard_name
            total_bytes += value.numel() * value.element_size()
        print(f"[{shard_idx + 1}/{len(order)}] {'globals' if group is None else f'layer {group} ({layer_types[group]})'}: "
              f"{len(hf)} tensors -> {shard_name}", flush=True)
        del state_dict, hf

    index = {"metadata": {"total_size": total_bytes}, "weight_map": dict(sorted(weight_map.items()))}
    (args.output_dir / "model.safetensors.index.json").write_text(json.dumps(index, indent=2))
    for pattern in BASE_FILES:
        for path in args.base_model.glob(pattern):
            if path.name != "model.safetensors.index.json":
                shutil.copy2(path, args.output_dir / path.name)
    (args.output_dir / "STABLE").touch()
    print(f"wrote {len(weight_map)} tensors, {total_bytes / 1e9:.1f} GB to {args.output_dir}")


if __name__ == "__main__":
    main()
