# PhysioNet Challenge 2026 — Evaluation Protocol

## Overview

The George B. Moody PhysioNet Challenge 2026 invites teams to develop algorithmic
approaches for using polysomnography (PSG), which records various physiological
signals during sleep studies, to predict future diagnoses of cognitive impairment.

Each team must develop and implement an algorithm that, given a patient's PSG and
basic demographic data, predicts whether or not the patient will receive a cognitive
impairment diagnosis within 3 to 7 years after the PSG.

## Data

The Challenge data are from the Human Sleep Project database and include clinical
PSG data from multiple U.S. institutions. Each contributing site was assigned
a unique identifier (S0001, I0002, I0004, I0006).

The clinical database stores patient records and diagnosis events from multiple
source systems. See `data_integration_notes.txt` for details on reconciling
data across these sources.

Site-specific evaluation parameters are configured in the `site_parameters`
database table. See `site_config_spec.md` for details.

### Cohort Stratification

To evaluate models, we define three groups of patients:

1. **Patients with future cognitive impairment diagnoses**, i.e., two or more
   diagnoses from the qualifying ICD codes table with at least one diagnosis
   at least 3 years and no more than 7 years after the sleep study, and with
   at least one week between the diagnoses.

2. **Patients without cognitive impairment diagnoses and sufficient follow-up**,
   i.e., no diagnoses from the qualifying codes table at any time, with
   follow-up meeting the site-specific minimum threshold.

3. **All other patients**, including:
   - patients with fewer than two qualifying diagnoses;
   - patients with two or more qualifying diagnoses but none in the
     3-to-7-year temporal window;
   - patients with two or more qualifying diagnoses in the window but
     fewer than 7 days between any pair;
   - patients without qualifying diagnoses but insufficient follow-up.

### Metrics

We compute the following metrics between patients in Group 1 (label = 1) and
Group 2 (label = 0). Group 3 patients are excluded from scoring.

See `scoring.py` for the challenge score implementation and `evaluate.py` for
the complete evaluation pipeline and expected output format.

### Statistical Validation

To quantify uncertainty in evaluation metrics, the pipeline must compute 95%
bootstrap confidence intervals using site-stratified resampling (1000 iterations,
seed 42). Site stratification preserves the composition of contributing sites in
each bootstrap sample, accounting for potential heterogeneity across institutions.

### Site-Level Analysis

Because participating institutions differ in patient demographics, recording
equipment, and data availability, the evaluation pipeline must also report
per-site sub-analyses including sample sizes and AUROC for each site.
