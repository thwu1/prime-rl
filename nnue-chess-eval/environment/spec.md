# NNUE Evaluator — Partial Specification

## Overview

This evaluator uses an Efficiently Updatable Neural Network (NNUE) to score chess
positions. The network weights are stored in `/app/network.bin`. A reference
oracle binary is available at `/app/nnue_oracle` for testing.

## Architecture Parameters

- **Input features**: 768 (2 relative colors x 6 piece types x 64 squares)
- **Hidden layer size** and **number of input buckets**: can be derived from the
  network binary file size (see formula below)
- **Quantization constants**: QA = 255, QB = 64
- **Evaluation scale**: SCALE = 400
- **Activation**: SCReLU, defined as `screlu(x) = clamp(x, 0, QA)^2`

## Network File Format

All values in `network.bin` are stored as **little-endian signed 16-bit integers**
(int16), packed contiguously in this order:

1. **Input weights** — shape `[num_buckets, 768, hidden_size]`, row-major
   (iterate over buckets, then input features, then hidden neurons)
2. **Input biases** — shape `[hidden_size]`
3. **Output weights** — shape `[2 * hidden_size]`
   (first `hidden_size` entries for the side-to-move accumulator,
    next `hidden_size` entries for the opponent accumulator)
4. **Output bias** — shape `[1]`

File size in bytes:
`2 * (num_buckets * 768 * hidden_size + hidden_size + 2 * hidden_size + 1)`

## Feature Indexing

Each piece on the board produces one feature index per perspective:

    feature_index = relative_color * 384 + piece_type_index * 64 + adjusted_square

- **Piece type indices**: pawn=0, knight=1, bishop=2, rook=3, queen=4, king=5
- **Relative color**: 0 when the piece's color matches the perspective
  (e.g. white pawn from white's perspective); 1 when opposite
- **Square convention**: a1=0, b1=1, ... h1=7, a2=8, ... h8=63

### Square Adjustment

- **White perspective**: the piece's square is used directly.
- **Black perspective**: flip the rank by XOR-ing with 56 (`sq ^ 56`).

## Input Bucketing

The perspective king's square determines which slice of input weights to use.
A lookup table maps each of the 64 (possibly rank-flipped) king squares to a
bucket index. The exact contents of this lookup table are not provided here;
they must be determined empirically using the oracle.

- For white: `bucket = lookup[white_king_square]`
- For black: `bucket = lookup[black_king_square ^ 56]`

## Forward Pass

1. **Build accumulators** for both white and black perspectives:

       acc[h] = input_bias[h] + sum(input_weights[bucket][feat][h]
                                    for each active feature)

2. **Assign perspectives**: if white to move, `us = white_acc`, `them = black_acc`;
   otherwise swap.

3. **Compute output**:

       output = sum over h of:
           screlu(us[h]) * output_weights[h]
         + screlu(them[h]) * output_weights[hidden_size + h]

4. **Quantize to raw evaluation**:

       raw_eval = (output / QA + output_bias) * SCALE / (QA * QB)

   All integer divisions round toward negative infinity (floor division).

## Evaluation Scaling

Two scaling steps are applied **in order** after the forward pass:

1. **Material phase scaling**:
   - Phase weights: pawn=0, knight=3, bishop=3, rook=5, queen=10, king=0
   - `material_phase` = sum of phase weights for every piece on the board
   - `eval = eval * (22400 + material_phase) / 32768`

2. **Fifty-move rule scaling**:
   - `eval = eval * (200 - halfmove_clock) / 200`

   All integer divisions round toward negative infinity (floor division).

## Oracle Commands

    /app/nnue_oracle eval <FEN>        # integer evaluation for the position
    /app/nnue_oracle features <FEN>    # sorted feature indices, both perspectives
    /app/nnue_oracle probe <FEN>       # evaluation + features combined
