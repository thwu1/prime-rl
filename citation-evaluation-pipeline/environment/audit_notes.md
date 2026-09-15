# Evaluation Audit Notes

## Background
The evaluation environment at `/app/` contains data from LegalCiteBench, a benchmark
measuring legal citation reliability in language model outputs. It covers three task
categories (Cat1: citation retrieval, Cat2: citation completion, Cat3: citation error
detection) across multiple US legal jurisdictions.

## Data Architecture
The evaluation data has been distributed across multiple formats and sources:

- **SQLite database** (`/app/citation_eval.db`): Contains instance metadata and model
  responses. Ground truth is NOT stored in the database — it was moved to a separate
  manifest file.

- **Ground truth manifest** (`/app/ground_truth_manifest.jsonl`): Contains ground truth
  annotations for each instance in a nested JSONL format. Each line is a JSON object
  with `instance_id`, `category`, and `annotations` fields.

- **Citation authority index** (`/app/citation_authority.xml`): Maps parallel citations
  — different reporter references that point to the same judicial decision. Essential
  for correct citation matching across reporter systems.

- **Scoring configuration**: Split between `/app/scoring_config.yaml` (base parameters)
  and `/app/scoring_overrides.json` (overrides including MAR threshold and parallel
  citation settings).

## Known Issues

1. **Broken evaluation script**: The existing evaluation script at `/app/evaluate.py`
   was adapted from a prior evaluation pipeline that assumed ground truth was stored
   in the database. It crashes because the `ground_truth` table no longer exists.

2. **Incomplete citation extraction**: The existing script only handles three citation
   formats (U.S., F., S.W.) but the dataset spans 20+ reporter systems including
   regional, state-specific, and neutral citation formats.

3. **Missing parallel citation resolution**: The evaluation must use the authority
   index to resolve parallel citations (same case in different reporters).

4. **Cat3 scoring issues**: The Cat3 scoring in the existing script does not scale
   raw scores to the 0-100 reporting scale. It also lacks negation handling for
   the "true" variant.

5. **Configuration fragmentation**: Scoring parameters are split across YAML and JSON
   files that must be merged (JSON overrides take precedence).

## Expected Output
Build a corrected evaluation pipeline and write results to `/app/results.json`.
