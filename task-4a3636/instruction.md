A Python implementation of NIST NFIQ 2-compatible fingerprint image quality
feature extraction is at `/app/nfiq2_features.py`. It computes Orientation
Certainty Level (OCL) and Frequency Domain Analysis (FDA) quality measures
on synthetic PGM fingerprint images in `/app/images/`, along with contrast
metrics (Mu and MMB).

The implementation produces incorrect quality scores for some or all images.
Excerpts of the authoritative NIST NFIQ2 C++ reference source are available
in `/app/reference/` for algorithm-level comparison.

Fix the Python implementation so that running `python3 /app/nfiq2_features.py`
writes correct, reference-conformant results to `/app/output.json`.