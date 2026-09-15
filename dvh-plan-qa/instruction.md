You are performing a multi-site clinical trial QA audit of head-and-neck IMRT treatment plans. Patient submissions are in `/app/data/` — each patient directory contains a 3D dose grid (`dose.nii.gz`) and structure contour masks under `structures/`. The clinical trial protocol is at `/app/data/protocol.txt`.

Data was submitted by different clinical sites with varying conventions. Produce a complete dosimetric audit by writing these files to `/app/output/`:

- `name_mapping.csv` — columns: `patient,original_name,standard_name` (original_name = file stem; only structures mapping to protocol-defined standard names)
- `dvh_metrics.csv` — columns: `patient,structure,D95,D50,D2,D98,Dmean,Dmax,V5,V20,Dcc1` (structure = TG-263 name; doses in Gy; volumes in %)
- `qa_report.csv` — columns: `patient,structure,constraint,limit,actual,status` (status = PASS or FAIL; one row per protocol constraint per patient, including the HI constraint for PTV)

All reported values must be in Gray and percent. The audit must correctly handle any data anomalies present in the submissions.

Do not use platipy, pymedphys, or dicompyler-core.