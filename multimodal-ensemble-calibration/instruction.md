Six neural networks, each trained on a different sensory modality, produce raw logits for 32-class micro-gesture recognition. You have access to their outputs on a labeled validation set and an unlabeled test set.

## Data

`/app/data/` contains:

- `val_logits.npy` — `(6, 600, 32)` float64: raw logits from 6 models on 600 validation samples
- `test_logits.npy` — `(6, 250, 32)` float64: raw logits on 250 test samples
- `val_labels.npy` — `(600,)` int64: ground-truth class indices (0–31) for validation
- `model_info.json` — model metadata including names, modalities, architectures, and class names

`numpy` is pre-installed.

## Objective

Produce test-set class predictions that:
1. Achieve **>= 68% top-1 accuracy**.
2. **Strictly exceed** the top-1 accuracy of naive probability averaging (independently softmax each model's raw logits, average the resulting 6 probability vectors, take argmax).

## Required Output

### `/app/output/test_predictions.csv`
Exactly 250 lines. Each line: one integer (predicted class index 0–31). No header.

### `/app/output/ensemble_config.json`
JSON object with these exact keys:

- `"scaling_factors"` — list of 6 positive floats, each in (0.01, 100.0); the ratio max/min across the 6 values must exceed 1.5
- `"weights"` — list of 6 non-negative floats summing to 1.0 (±0.05 tolerance); at least one must differ from uniform (1/6) by more than 0.02
- `"method"` — non-empty string describing the approach