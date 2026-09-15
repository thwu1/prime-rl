A compiled chess position evaluator is at `/app/nnue_oracle`. It uses an NNUE (Efficiently Updatable Neural Network) architecture with quantized weights stored in `/app/network.bin`. A partial specification of the architecture is at `/app/spec.md`.

The oracle accepts these commands:

    /app/nnue_oracle eval <FEN>        # prints integer centipawn evaluation
    /app/nnue_oracle features <FEN>    # prints sorted feature indices per perspective
    /app/nnue_oracle probe <FEN>       # prints evaluation and features together

The specification describes the network architecture but contains errors and omissions. Use the oracle binary to verify your understanding and resolve discrepancies between the spec and the oracle's actual behavior.

Complete `/app/nnue.py` so that for any valid FEN position it produces output identical to the oracle. The module must expose:

- `evaluate(fen: str) -> int` — integer centipawn score from the side-to-move's perspective
- `get_features(fen: str, white_perspective: bool) -> list[int]` — sorted list of active input feature indices for the given perspective