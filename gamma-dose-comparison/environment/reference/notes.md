# Gamma Index for Radiation Therapy QA

The gamma index is a standard metric for quantitative comparison of dose
distributions in radiation therapy quality assurance. It was introduced by
Low et al. (1998, Medical Physics 25(5)) to address the limitations of
evaluating dose distributions using dose difference or distance-to-agreement
criteria alone.

## Concept

Traditional dose comparison methods have complementary weaknesses:
- **Dose difference** (DD) works well in low-gradient regions but is overly
  sensitive in high-gradient regions (e.g., beam penumbra).
- **Distance-to-agreement** (DTA) works well in high-gradient regions but
  is insensitive in low-gradient regions.

The gamma index combines both criteria into a single pass/fail metric.
For each reference point, it searches the evaluation distribution for
the closest match in a combined dose-distance space.

## Interpretation

- gamma <= 1: The reference point passes -- the evaluation distribution
  agrees within the specified tolerances.
- gamma > 1: The reference point fails.
- Common clinical criteria: "3%/3mm" means 3% dose tolerance and 3mm
  distance tolerance.

## Pass Rate

The overall quality metric is the **gamma pass rate**: the percentage of
evaluated reference points where gamma <= 1. Clinical thresholds typically
require >90-95% pass rate.

## Normalization Modes

- **Global**: Dose differences are normalized to a single value (typically
  the maximum reference dose). Provides consistent scaling across all
  points.
- **Local**: Dose differences are normalized to the local reference dose
  at each point. More stringent in low-dose regions.

## Low-Dose Exclusion

Reference points below a specified threshold percentage of the
normalization value are typically excluded from analysis, as these
regions have poor signal-to-noise ratios and limited clinical relevance.
