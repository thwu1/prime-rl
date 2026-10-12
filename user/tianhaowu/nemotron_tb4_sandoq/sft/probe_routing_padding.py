"""Measure the trainer's Max Vio statistic on real tokens with and without fixed_stack padding.

Loads only the first few Nemotron-H layers (HF implementation) on one GPU, renders one training
row exactly like SFTDataset, and applies prime-rl's get_load_balance_stats formula to the router's
top-k selections for (a) the real tokens and (b) the same row padded with token 0 to --padded-len.
"""

import argparse
import json

import torch
from datasets import load_dataset
from renderers.base import create_renderer
from renderers.configs import Nemotron3RendererConfig
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer
from transformers.models.nemotron_h import modeling_nemotron_h

from prime_rl.configs.sft import LossMaskConfig
from prime_rl.trainer.models.nemotron_h.modeling_nemotron_h import _patch_mamba2_use_triton_ssd
from prime_rl.trainer.sft.data import SFTDataset


def max_vio(tokens_per_expert: torch.Tensor, top_k: int) -> float:
    rest = tokens_per_expert.sort(descending=True).values[top_k:]
    balanced = rest.mean()
    return ((rest.max() - balanced) / balanced).item()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--lengths", required=True)
    parser.add_argument("--num-layers", type=int, default=7)
    parser.add_argument("--target-len", type=int, default=20000)
    parser.add_argument("--padded-len", type=int, default=262144)
    args = parser.parse_args()

    _patch_mamba2_use_triton_ssd()
    # prime-rl patches the modular class; AutoModel instantiates the modeling class.
    from transformers.models.nemotron_h import modular_nemotron_h

    modeling_nemotron_h.NemotronHMamba2Mixer.forward = modular_nemotron_h.NemotronHMamba2Mixer.forward
    config = AutoConfig.from_pretrained(args.model)
    config.layers_block_type = config.layers_block_type[: args.num_layers]
    model = AutoModelForCausalLM.from_pretrained(
        args.model, config=config, dtype=torch.bfloat16, device_map="cuda"
    ).eval()

    selections: list[torch.Tensor] = []
    original = modeling_nemotron_h.NemotronHMoE.route_tokens_to_experts

    def capture(self, router_logits):
        topk_indices, topk_weights = original(self, router_logits)
        selections.append(topk_indices.detach())
        return topk_indices, topk_weights

    modeling_nemotron_h.NemotronHMoE.route_tokens_to_experts = capture

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    renderer = create_renderer(
        tokenizer,
        Nemotron3RendererConfig(
            enable_thinking=True,
            preserve_all_thinking=True,
            truncate_history_thinking=False,
            normalize_tool_response_wrappers=False,
            ultra=False,
        ),
    )
    dataset = load_dataset(args.data, None, split="train")
    lengths = json.load(open(args.lengths))
    trace_id = min(lengths, key=lambda t: abs(lengths[t] - args.target_len))
    example = dataset[dataset["trace_id"].index(trace_id)]
    sft = SFTDataset(dataset, tokenizer, shuffle=False, seq_len=args.padded_len, loss_mask_config=LossMaskConfig(),
                     renderer=renderer)
    input_ids = sft._process(dict(example))["input_ids"]
    print(f"trace={trace_id} real_tokens={len(input_ids)} padded_len={args.padded_len}")

    num_experts, top_k = config.n_routed_experts, config.num_experts_per_tok
    for label, ids in (("real", input_ids), ("padded", input_ids + [0] * (args.padded_len - len(input_ids)))):
        selections.clear()
        with torch.no_grad():
            model.model(input_ids=torch.tensor([ids], device="cuda"), use_cache=False)
        per_layer = []
        for topk_indices in selections:
            counts = torch.bincount(topk_indices.flatten(), minlength=num_experts).float()
            per_layer.append(max_vio(counts, top_k))
        real_counts = [torch.bincount(t[: len(input_ids)].flatten(), minlength=num_experts).float() for t in selections]
        pad_part = [
            torch.bincount(t[len(input_ids) :].flatten(), minlength=num_experts) for t in selections
        ] if label == "padded" else []
        print(
            f"{label:>6}: per-MoE-layer max_vio={[round(v, 1) for v in per_layer]} "
            f"mean={sum(per_layer) / len(per_layer):.1f}"
        )
        if pad_part:
            for layer, counts in enumerate(pad_part):
                top = counts.sort(descending=True).values
                print(
                    f"        layer {layer}: pad tokens routed to {int((counts > 0).sum())} experts; "
                    f"top-22 share={top[:top_k].sum().item() / counts.sum().item():.3f}, "
                    f"23rd-expert load={int(top[top_k])} vs real-token mean load={real_counts[layer].mean().item():.0f}"
                )


if __name__ == "__main__":
    main()
