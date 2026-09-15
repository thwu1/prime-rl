Build a text watermarking system and evaluation pipeline for the political speech corpus at `/app/data/corpus.jsonl`. A synonym dictionary is at `/app/data/synonyms.json` and attack scripts at `/app/attacks/attack.py` define the operational environment.

## Components

### 1. `/app/watermark.py` — Watermark embedder and detector

CLI with two subcommands:

- `python3 /app/watermark.py embed --key KEY --input FILE --output FILE`
  Takes input JSONL (fields: `id`, `text`) and outputs JSONL with watermarked text. The watermark must be key-dependent and preserve text readability.

- `python3 /app/watermark.py detect --key KEY --input FILE --output FILE`
  Takes input JSONL and outputs JSONL with fields `id` and `label` (1.0 = watermarked, 0.0 = not watermarked).

### 2. `/app/evaluate.py` — TWF evaluation script

```
python3 /app/evaluate.py --original FILE --watermarked FILE --detection FILE --ground-truth FILE --output FILE
```

Computes and writes a JSON file with:
- `twf`: Text Watermarking Fidelity = `bleu * balanced_accuracy`
- `bleu`: sentence-level BLEU (4-gram with smoothing), averaged across documents
- `balanced_accuracy`: `(TPR + TNR) / 2`
- `confusion`: `[[TN, FP], [FN, TP]]`

Ground truth is JSONL with `id` and `label` fields.

## Requirements

- The watermark must survive attacks from `/app/attacks/attack.py` (unicode normalization, character perturbation, mixed)
- BLEU between original and watermarked text must be high (synonym-level changes only)
- Detection must be key-dependent: using the wrong key must not trigger false positives
- The system must work on arbitrary JSONL texts following the corpus format