A researcher's optimization workspace at `/app/lab/` contains an incomplete analysis of a combinatorial dice-shutting game. The active challenge experiment's parameters are distributed across a compressed database backup, an AES-encrypted scoring configuration, and base64-encoded database entries. Read the researcher's journal at `/app/lab/notes/researcher_journal.txt` and the metadata registry at `/app/lab/configs/metadata_registry.json` to understand the data layout and recovery steps.

**Game rules:** On each turn the player chooses one available dice option and rolls. They must then shut (close) a non-empty subset of currently-open tiles whose face values sum exactly to the roll total. If no valid subset exists, the game ends and the player's score equals the weighted penalty of all remaining open tiles. A score of 0 means all tiles were shut (a perfect game). Under optimal play the player minimizes expected final score at every decision point, choosing both which dice to roll and which subset of tiles to shut.

Recover the experiment parameters and compute the following under the cost-optimal policy:

1. The exact expected score as a fraction p/q in lowest terms (gcd(p,q)=1, p>=0, q>0)
2. The exact probability of a perfect game (score 0) under the cost-optimal policy, as a fraction a/b in lowest terms (gcd(a,b)=1, a>=0, b>0)
3. The number of non-empty tile states where the cost-optimal dice choice differs from the dice that is optimal at the starting state (all tiles open)

Write results to `/app/answer.txt` with exactly six lines:
```
p
q
a
b
optimal_start_dice_label
policy_divergence_count
```