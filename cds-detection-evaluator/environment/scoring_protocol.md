# Composite Scoring Methodology

## Background: Composite Detection Score (CDS)

The Argoverse 2 3D detection challenge ranks models using a Composite Detection
Score that combines classification quality with estimation accuracy. Study the
detection evaluation reference at `/app/reference/detection_eval.py` to understand
how CDS is computed and what design principles it follows.

Key elements of the CDS approach:
- A classification quality term (mAP) that measures detection/classification ability
- True-positive error scores, each normalized to [0,1] using domain-appropriate thresholds
- A multiplicative combination ensuring both classification and estimation quality matter
- Exactly three error-quality components, each with a normalization threshold derived
  from the metric's physical domain

## Adapting CDS to Scene Flow: Composite Scene Flow Score (CSFS)

Derive a Composite Scene Flow Score following the same structural principle as CDS.

**Classification Quality Term**: In detection, mAP measures how well the model
identifies objects. For scene flow, identify the metric that measures how well a
model classifies points as dynamic vs. static. This metric should be 0 when the
model cannot distinguish dynamic from static points, and 1 for perfect classification.

**Error-Quality Components**: The composite score uses exactly three error-quality
components (matching the three TP error types in CDS). For each component, apply
the same normalization principle as CDS — use domain-appropriate thresholds matching
those used for analogous error types in the detection challenge (study the detection
code to identify the normalization constants for translation-type and orientation-type
errors):

- Error metrics (where lower is better) should be converted to scores using
  `max(0, 1 - error / threshold)` with a physically meaningful threshold
- Quality metrics (where higher is better and already in [0,1]) can serve as
  scores directly. Where two related quality metrics exist for the same aspect
  of flow estimation, combine them into a single component

**Combination**: Follow the CDS structure: multiply the classification quality
term by the arithmetic mean of the three component scores.

## 3-Way Averages

Each metric's "3-Way Average" is the arithmetic mean computed over three
class/motion groups:
1. Foreground / Dynamic
2. Foreground / Static
3. Background / Static

Background / Dynamic is excluded from all evaluation.

Each group's metric value is the count-weighted mean of per-point values across
all sweeps and both distance categories (Close and Far).
