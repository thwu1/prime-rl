"""Fix all numerical issues in the training pipeline.

Fixes:
1. model.py: Embedding scaling uses int(math.sqrt(dim)) which truncates
   the scale factor for non-perfect-square dimensions.
   Fix: Use math.sqrt(dim) directly.

2. trainer.py: Gradient accumulation uses naive 1/ga_steps scaling of
   per-minibatch mean losses, which gives wrong results when minibatches
   have different numbers of non-padding tokens.
   Fix: Pre-compute total token count across all minibatches and use
   sum reduction / total_tokens for each minibatch.
"""

import sys


def fix_model():
    """Fix embedding scaling truncation in model.py."""
    with open("/app/model.py", "r") as f:
        content = f.read()

    old = "x = self.embedding(input_ids) * int(math.sqrt(self.dim))"
    new = "x = self.embedding(input_ids) * math.sqrt(self.dim)"

    if old not in content:
        print("WARNING: Could not find embedding scaling bug in model.py", file=sys.stderr)
        return

    content = content.replace(old, new)

    with open("/app/model.py", "w") as f:
        f.write(content)
    print("Fixed embedding scaling in model.py: int(sqrt(dim)) -> sqrt(dim)")


def fix_trainer():
    """Fix gradient accumulation normalization in trainer.py."""
    with open("/app/trainer.py", "r") as f:
        content = f.read()

    old_block = """        accumulated_loss = 0.0
        for i, mb in enumerate(minibatches):
            logits = self.model(mb["input_ids"])
            loss = self.compute_loss(logits, mb["labels"])

            # Scale loss by 1/ga_steps before backward to produce
            # correctly averaged gradients across accumulation steps
            scaled_loss = loss / self.ga_steps
            scaled_loss.backward()

            accumulated_loss += loss.item()

        self.optimizer.step()

        return accumulated_loss / self.ga_steps"""

    new_block = """        # Pre-compute total token count across ALL GA steps for correct normalization.
        # This ensures each minibatch loss is normalized by the same global
        # denominator, making sum_g [sum(CE_in_g)/N_total] = sum(CE)/N_total.
        total_tokens = sum(self.count_tokens(mb) for mb in minibatches)

        accumulated_loss = 0.0
        for i, mb in enumerate(minibatches):
            logits = self.model(mb["input_ids"])
            # Use total_tokens for normalization: sum reduction / N_total
            loss = self.compute_loss(
                logits, mb["labels"], num_items_in_batch=total_tokens
            )
            # No 1/ga_steps scaling needed: total_tokens normalization handles it
            loss.backward()

            accumulated_loss += loss.item()

        self.optimizer.step()

        # Sum of per-minibatch losses = sum(CE) / N_total = full-batch loss
        return accumulated_loss"""

    if old_block not in content:
        print("WARNING: Could not find GA normalization bug in trainer.py", file=sys.stderr)
        return

    content = content.replace(old_block, new_block)

    with open("/app/trainer.py", "w") as f:
        f.write(content)
    print("Fixed GA normalization in trainer.py: pre-compute total tokens across all minibatches")


if __name__ == "__main__":
    fix_model()
    fix_trainer()
