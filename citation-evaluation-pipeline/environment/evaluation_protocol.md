# LegalCiteBench Evaluation Protocol

## Task Categories

- **Cat1 (Citation Retrieval)**: Given a legal question, the model provides relevant judicial citations.
- **Cat2 (Citation Completion)**: Given a legal question with some citations already identified, the model provides additional relevant citations.
- **Cat3 (Citation Error Detection)**: Given a legal analysis paragraph containing a citation, the model determines whether the citation is correct or corrupted, and if corrupted, identifies the error.

## Data

The benchmark data is stored in a normalized SQLite database at `/app/citation_eval.db`. Explore the schema to understand the data model and relationships between tables. Ground truth for Cat1/Cat2 instances is stored as individual citation entries, not aggregated.

## Cat1/Cat2 Scoring: Citation-Level F1

1. **Citation Extraction**: Extract all legal citation strings from the model's response text. The dataset spans citations from federal, regional, state, and neutral citation systems across US jurisdictions. You will need to examine the ground truth data to determine the full range of citation formats represented.

2. **Matching**: A predicted citation matches a ground truth citation via bidirectional case-insensitive substring matching: a match occurs if either string is a substring of the other (case-insensitive).

3. **F1 Computation**: For each instance, compute precision (matched predictions / total predictions) and recall (matched predictions / total ground truth). Compute F1 = 2 * precision * recall / (precision + recall), or 0 if both are 0. Report mean F1 across instances, scaled per scoring configuration.

## Cat3 Scoring: Error Detection

Rule-based scoring on a raw scale. See `/app/scoring_config.yaml` for the raw score maximum and reporting scale.

**"true" variant** (the citation in the paragraph is correct):
- **Score 2** if the model falsely claims an error — i.e., output contains "error", "incorrect", or "wrong" (case-insensitive) unless preceded by a negation such as "no error"
- **Score 5** if the model correctly confirms the citation — i.e., output contains "correct" or "accurate" (case-insensitive)
- **Score 0** otherwise

**"fake" variant** (the citation has been corrupted):
- **Score 1** if the model fails to detect the error (output does not contain "error", "incorrect", or "wrong")
- **Score 5** if the model detects the error AND the correct citation (extracted from the ground truth text) appears in the model output (case-insensitive substring match)
- **Score 2** if the model detects the error but does not include the correct citation

## Misleading Answer Rate (MAR)

MAR measures how often models produce concrete but low-quality citations rather than abstaining.

**Definition**: MAR = (number of low-scoring AND concrete responses) / (number of low-scoring responses)

Where:
- A response is **low-scoring** if its F1 score (scaled) is at or below the threshold defined in `/app/scoring_config.yaml`
- A response is **concrete** if at least one legal citation was extracted from the model output
- If there are no low-scoring responses, MAR = 0

Compute MAR separately for Cat1, Cat2, and overall (Cat1 + Cat2 combined).

## Output

Write results to `/app/results.json`:
```json
{
  "cat1_mean_f1": "<float, scaled>",
  "cat2_mean_f1": "<float, scaled>",
  "cat3_mean_score": "<float, scaled>",
  "cat1_mar": "<float, 0-1>",
  "cat2_mar": "<float, 0-1>",
  "overall_mar": "<float, 0-1>",
  "num_instances": "<int, total instances processed>"
}
```
