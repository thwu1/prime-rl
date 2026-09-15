A 4-bit NormalFloat (NF4) weight quantization library is at `/app/nf4_quant/` with two modules:

- `quantization.py` — builds the NF4 lookup table from N(0,1) quantiles, performs block-wise quantization/dequantization with per-block absmax scaling, and compresses scaling factors via secondary 8-bit block-wise quantization
- `memory.py` — computes parameter counts and memory footprints for LLaMA-family models at various precisions (fp32, fp16, nf4, nf4+double-quantization)

Model architectures are defined in `/app/config.json`. The implementation has multiple bugs across both modules producing wrong quantization outputs and incorrect memory estimates. Find and fix all bugs so that the library yields numerically accurate quantization roundtrips, recovers double-quantized scaling factors faithfully, and computes exact parameter counts and memory footprints for all configured model sizes.