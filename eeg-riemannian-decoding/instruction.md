Synthetic motor imagery EEG recordings from multiple subjects are in `/app/data/`. Each `subject_XX.npz` file contains `data` (trials x channels x time samples) and `labels` (binary: 0 or 1). Dataset metadata is in `/app/data/metadata.npz`. The data generation script at `/opt/generate_data.py` can regenerate the data if needed.

Create `/app/pipeline.py` that exposes a callable `cross_subject_decode(data_dir='/app/data')`. This function must perform leave-one-subject-out cross-validation -- each subject serves as the test set exactly once, with all remaining subjects used for training -- and write results to `/app/results.json` containing:

- `accuracies`: list of per-subject float accuracies
- `mean_accuracy`: float, the overall mean
- `n_subjects`: int
- `method`: string describing the approach

Execute the pipeline so that `/app/results.json` exists.

**Requirements:**
- Mean cross-subject accuracy must exceed **0.58** (chance level is 0.50)
- Every individual subject accuracy must exceed **0.42**
- Direct pooling of features across subjects yields near-chance accuracy on this dataset