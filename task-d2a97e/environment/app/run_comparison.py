"""Compare full-batch training vs gradient accumulation training.

This script demonstrates that gradient accumulation with variable-length
sequences produces different loss values than full-batch training with
the same effective batch size. The discrepancy is systematic and grows
with the variance in sequence lengths.
"""

import torch
import copy
from model import SmallCausalLM
from dataset import create_dataset, collate_sequences
from trainer import Trainer


def run_comparison(ga_steps=4, num_samples=16, min_len=10, max_len=80, seed=42, lr=0.01):
    """Run a single comparison between full-batch and GA training."""
    torch.manual_seed(seed)
    model = SmallCausalLM(vocab_size=512, dim=64, hidden_dim=128, n_layers=2)

    sequences = create_dataset(
        num_samples=num_samples,
        vocab_size=512,
        min_len=min_len,
        max_len=max_len,
        seed=seed,
    )
    batch = collate_sequences(sequences)

    # Print sequence length distribution
    lengths = [len(s) for s in sequences]
    print(f"Sequence lengths: min={min(lengths)}, max={max(lengths)}, "
          f"mean={sum(lengths)/len(lengths):.1f}, std={torch.tensor(lengths, dtype=torch.float).std():.1f}")

    # Clone model for fair comparison
    model_fb = copy.deepcopy(model)
    model_ga = copy.deepcopy(model)

    # Full batch training
    trainer_fb = Trainer(model_fb, lr=lr, ga_steps=1)
    loss_fb = trainer_fb.train_step_full_batch(batch)

    # Gradient accumulation
    trainer_ga = Trainer(model_ga, lr=lr, ga_steps=ga_steps)
    loss_ga = trainer_ga.train_step_ga(batch)

    # Compare
    loss_diff = abs(loss_fb - loss_ga)
    print(f"Full batch loss:     {loss_fb:.10f}")
    print(f"GA loss (steps={ga_steps}):   {loss_ga:.10f}")
    print(f"Loss difference:     {loss_diff:.2e}")

    # Compare weights
    max_weight_diff = 0.0
    for (name, p_fb), (_, p_ga) in zip(
        model_fb.named_parameters(), model_ga.named_parameters()
    ):
        diff = (p_fb - p_ga).abs().max().item()
        max_weight_diff = max(max_weight_diff, diff)

    print(f"Max weight diff:     {max_weight_diff:.2e}")

    return loss_diff, max_weight_diff


def main():
    print("=" * 65)
    print("Gradient Accumulation vs Full Batch Training Comparison")
    print("=" * 65)

    print("\n--- Test 1: Variable-length sequences, GA=4 ---")
    ld1, wd1 = run_comparison(ga_steps=4, num_samples=16, min_len=10, max_len=80)

    print("\n--- Test 2: High length variance, GA=4 ---")
    ld2, wd2 = run_comparison(ga_steps=4, num_samples=16, min_len=5, max_len=200, seed=123)

    print("\n--- Test 3: Equal-length sequences (control), GA=4 ---")
    ld3, wd3 = run_comparison(ga_steps=4, num_samples=16, min_len=50, max_len=50, seed=99)

    print("\n--- Test 4: More GA steps, GA=8 ---")
    ld4, wd4 = run_comparison(ga_steps=8, num_samples=24, min_len=10, max_len=100, seed=777)

    print("\n" + "=" * 65)
    print("Summary:")
    print(f"  Test 1 (variable lengths):  loss_diff={ld1:.2e}, weight_diff={wd1:.2e}")
    print(f"  Test 2 (high variance):     loss_diff={ld2:.2e}, weight_diff={wd2:.2e}")
    print(f"  Test 3 (equal lengths):     loss_diff={ld3:.2e}, weight_diff={wd3:.2e}")
    print(f"  Test 4 (ga=8):              loss_diff={ld4:.2e}, weight_diff={wd4:.2e}")

    all_match = all(d < 1e-6 for d in [ld1, ld2, ld3, ld4])
    if all_match:
        print("\nAll tests PASS: GA matches full-batch training.")
    else:
        print("\nFAILURE: GA does NOT match full-batch training.")
        if ld3 < 1e-6:
            print("  Note: Equal-length sequences match (Test 3), but variable-length")
            print("  sequences do not. The bug manifests when minibatches have different")
            print("  numbers of non-padding tokens.")


if __name__ == "__main__":
    main()
