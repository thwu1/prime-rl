16,384 neural network weights have been quantized to a 4-bit NormalFloat format with per-block absmax scaling. The 16-element codebook follows the QLoRA NF4 construction, parameterized by an unknown scalar α ∈ (0.5, 1). The binary file `/app/quantized_data.bin` contains a small header followed by per-block float32 scale factors and packed 4-bit indices.

Reverse-engineer the NF4 quantization, then design a Lloyd-Max optimal 4-bit quantizer for the same weights using the same per-block absmax scaling, and evaluate which scheme achieves superior quantization quality.

Files in `/app/`:
- `quantized_data.bin` — packed binary quantized representation
- `original_weights.bin` — 16,384 float32 weights (little-endian)
- `metadata.json` — basic format parameters

Write results to `/app/output/`:
- `codebook.json` — 16 NF4 codebook values (JSON array, sorted ascending)
- `alpha.txt` — recovered α (minimum 6 decimal places)
- `dequantized.bin` — NF4 dequantized weights as little-endian float32
- `error_metrics.json` — JSON with keys `mse`, `max_abs_error`, `sqnr_db` (= 10·log₁₀(mean(x²)/MSE))
- `lloyd_max_codebook.json` — 16 Lloyd-Max optimal reconstruction levels (JSON array, sorted ascending), trained on per-block-normalized weights
- `lloyd_max_dequantized.bin` — Lloyd-Max dequantized weights as little-endian float32
- `lloyd_max_metrics.json` — JSON with keys `mse`, `max_abs_error`, `sqnr_db`
- `comparison.json` — JSON with keys `nf4_mse`, `lloyd_max_mse`, `nf4_sqnr_db`, `lloyd_max_sqnr_db`, `mse_winner` ("nf4" or "lloyd_max"), `mse_improvement_pct` (percentage improvement of winner over loser), `sqnr_winner`
- `optimal_alpha.txt` — α minimizing re-quantization MSE for these weights (minimum 4 decimal places)