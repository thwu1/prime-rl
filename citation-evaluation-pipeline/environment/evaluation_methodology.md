# LegalCiteBench Evaluation Methodology Reference

## Overview
This evaluation implements programmatic scoring for the LegalCiteBench protocol
(Chen et al., 2025), a benchmark measuring closed-book citation reliability in
legal language models. The benchmark covers three citation-centric task categories
evaluated through distinct scoring rubrics.

## Data Architecture
Evaluation data spans multiple sources requiring reconciliation:
- Model responses and instance metadata reside in a SQLite database at `/app/citation_eval.db`
- Ground truth annotations are stored in a JSONL manifest at `/app/ground_truth_manifest.jsonl` with nested annotation fields
- A citation authority index at `/app/citation_authority.xml` maps parallel citations — different reporter references to the same judicial decision
- Scoring configuration is split across `/app/scoring_config.yaml` (base parameters) and `/app/scoring_overrides.json` (overrides); JSON values take precedence on conflicting keys

## Cat1/Cat2: Citation-Level F1
These categories measure citation retrieval (Cat1) and completion (Cat2). Scoring
uses citation-level F1 with bidirectional case-insensitive substring matching:
a match occurs if either string is a substring of the other.

When parallel citation resolution is enabled (see scoring overrides), citations
that reference the same case through different reporter systems must be treated
as equivalent matches. The authority index groups citations by case: if a predicted
citation belongs to the same authority group as a ground truth citation, the pair
constitutes a match.

The benchmark encompasses citations spanning:
- Federal reporters (U.S., F., F.Supp.)
- Regional reporter systems (S.W., N.W., N.E., S.E., So., A., P.)
- State-specific reporters across US jurisdictions
- Neutral citations (e.g., 2011 ND 159)
- Westlaw citations

Citation extraction patterns must cover the full range of formats represented in
the ground truth data. The dataset spans diverse jurisdictions and reporter systems;
examine the ground truth to determine the complete set of formats.

## Cat3: Citation Error Detection
Rule-based scoring evaluates whether models correctly identify citation errors in
legal analysis paragraphs. Instances use two variants:

- **"true" variant** (citation is correct): The model should confirm the citation.
  Negation patterns (e.g., "no error") must be distinguished from affirmative error
  claims.

- **"fake" variant** (citation has been corrupted): The model should detect the
  error and ideally provide the correct citation.

Raw scores on a 0-to-maximum scale are converted to the reporting scale specified
in the scoring configuration.

## Misleading Answer Rate (MAR)
MAR quantifies how often models provide concrete but low-quality citation responses
rather than abstaining:

    MAR = (low-scoring AND concrete responses) / (low-scoring responses)

A response is "low-scoring" if its scaled F1 is at or below the configured threshold.
A response is "concrete" if at least one citation was extracted from the model output.
If there are no low-scoring responses, MAR = 0.

MAR is computed separately for Cat1, Cat2, and overall (Cat1 + Cat2 combined).

## Output Format
Write results to `/app/results.json` containing:
- `cat1_mean_f1`, `cat2_mean_f1`, `cat3_mean_score`: floats on 0-100 scale
- `cat1_mar`, `cat2_mar`, `overall_mar`: floats on 0-1 scale
- `num_instances`: integer total count across all categories
