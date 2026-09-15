EEG motor imagery data from a brain-computer interface study is at `/app/data/`. The dataset contains 22-channel EEG recordings (250 Hz sampling rate) from 10 subjects performing 4 motor imagery tasks: left hand, right hand, feet, and tongue.

Training subjects (0–5) have both trial data and class labels in `/app/data/`. Test subjects (6–9) have trial data only — no labels are provided. Dataset details are in `/app/data/metadata.json`.

Data format:
- `subject_XX_trials.npy`: NumPy array, shape `(n_trials, 22, 750)`
- `subject_XX_labels.npy`: NumPy array, shape `(n_trials,)`, integers 0–3 (training subjects only)

Build a decoding pipeline that trains on subjects 0–5 and predicts motor imagery classes for subjects 6–9. Inter-subject variability in brain anatomy and neural signatures causes spatial distribution shifts across subjects that must be handled for cross-subject generalization.

Write results to `/app/results.json`:

```json
{
  "overall_accuracy": 0.0,
  "subject_accuracies": {"6": 0.0, "7": 0.0, "8": 0.0, "9": 0.0},
  "predictions": {"6": [0, 1, ...], "7": [0, 1, ...], "8": [0, 1, ...], "9": [0, 1, ...]}
}
```

Predictions must correspond to trials in the order they appear in `subject_XX_trials.npy`. Accuracy requirements: overall ≥ 50%, each test subject ≥ 30%.