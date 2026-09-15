"""Fix the gradient accumulation normalization bug in trainer.py.

The bug: When doing gradient accumulation with variable-length sequences, each
minibatch's loss is normalized by its OWN token count (via mean reduction), then
averaged across GA steps by dividing by ga_steps. This computes
(1/G) * sum(S_g / n_g), which is NOT equal to the full-batch loss
sum(S) / N_total when token counts n_g differ across minibatches.

The fix: Pre-compute total token count N_total across ALL minibatches.
Normalize each minibatch loss by N_total (via sum reduction / N_total).
No 1/ga_steps scaling is needed since N_total normalization already
yields the correct per-token loss that sums to the full-batch loss.

Mathematical proof:
  Full batch:  L = sum(CE) / N_total
  Fixed GA:    sum_g [sum(CE_in_g) / N_total] = sum(CE) / N_total = L
  Gradients:   sum_g d[sum(CE_in_g)/N_total]/dtheta = d[sum(CE)/N_total]/dtheta
"""

import re
import sys


def apply_fix():
    with open("/app/trainer.py", "r") as f:
        content = f.read()

    # The buggy train_step_ga method needs to be replaced with a version that:
    # 1. Pre-computes total tokens across all minibatches
    # 2. Uses num_items_in_batch=total_tokens for each minibatch loss
    # 3. Does NOT scale by 1/ga_steps (total_tokens normalization handles it)
    # 4. Returns the sum of per-minibatch losses (already correctly normalized)

    old_method = '''    def train_step_ga(self, batch):
        """Gradient accumulation training step.

        Splits the batch into self.ga_steps minibatches and accumulates
        gradients across them before performing a single optimizer step.

        This should produce mathematically equivalent results to
        train_step_full_batch() when called with the same data.

        Note: Gradients accumulate in float32 to minimize floating-point
        rounding during the accumulation process. The standard approach
        is to average the per-minibatch losses by dividing by ga_steps.

        Args:
            batch: Dict with 'input_ids' and 'labels' tensors

        Returns:
            Float loss value (should match train_step_full_batch)
        """
        self.model.train()
        self.optimizer.zero_grad()

        minibatches = split_batch(batch, self.ga_steps)

        accumulated_loss = 0.0
        for i, mb in enumerate(minibatches):
            logits = self.model(mb["input_ids"])
            loss = self.compute_loss(logits, mb["labels"])

            # Scale loss by 1/ga_steps before backward to produce
            # correctly averaged gradients across accumulation steps
            scaled_loss = loss / self.ga_steps
            scaled_loss.backward()

            accumulated_loss += loss.item()

        self.optimizer.step()

        return accumulated_loss / self.ga_steps'''

    new_method = '''    def train_step_ga(self, batch):
        """Gradient accumulation training step.

        Splits the batch into self.ga_steps minibatches and accumulates
        gradients across them before performing a single optimizer step.

        This produces mathematically equivalent results to
        train_step_full_batch() by normalizing each minibatch loss by the
        total token count across ALL minibatches, not per-minibatch counts.

        Args:
            batch: Dict with 'input_ids' and 'labels' tensors

        Returns:
            Float loss value (matches train_step_full_batch)
        """
        self.model.train()
        self.optimizer.zero_grad()

        minibatches = split_batch(batch, self.ga_steps)

        # Pre-compute total token count across ALL gradient accumulation steps.
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
            # No 1/ga_steps scaling needed: total_tokens normalization already
            # distributes the loss correctly across all minibatches
            loss.backward()

            accumulated_loss += loss.item()

        self.optimizer.step()

        # Sum of per-minibatch losses = sum(CE) / N_total = full-batch loss
        return accumulated_loss'''

    if old_method not in content:
        print("ERROR: Could not find the buggy train_step_ga method.", file=sys.stderr)
        print("The trainer.py file may have been modified already.", file=sys.stderr)
        sys.exit(1)

    new_content = content.replace(old_method, new_method)

    with open("/app/trainer.py", "w") as f:
        f.write(new_content)

    print("Fixed gradient accumulation normalization in trainer.py")


if __name__ == "__main__":
    apply_fix()
