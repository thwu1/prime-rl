A synthetic motor imagery EEG dataset is at `/app/data/` containing 10 subjects (22 channels, 250 Hz, 4-second epochs). Subjects 01-07 are training (labels provided in `labels.npy`), subjects 08-10 are test (labels withheld). Each trial belongs to one of two classes: left hand motor imagery (0) or right hand motor imagery (1). Subjects exhibit different amplitude profiles and noise characteristics, simulating realistic inter-individual variability in electrode impedance and neural signal strength.

Build a decoding pipeline that generalizes across subjects and predicts the motor imagery class for every trial of each test subject. Naive approaches that ignore inter-subject domain shift will not meet the accuracy threshold.

Produce:
- `/app/predictions.json` — `{"subject_08": [0, 1, ...], "subject_09": [...], "subject_10": [...]}` with integer class labels in trial order matching `eeg_data.npy`
- `/app/pipeline_config.json` — `{"preprocessing": "...", "feature_extraction": "...", "domain_adaptation": "...", "classifier": "..."}` describing each pipeline stage as a non-empty string

Mean balanced accuracy across test subjects must be >= 0.70, with each individual test subject >= 0.60.

Dataset metadata and channel layout are in each subject's `metadata.json` and in `/app/data/dataset_info.json`.