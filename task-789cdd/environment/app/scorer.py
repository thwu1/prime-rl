"""
Scorer Module - CCS Clinical Simulation Engine

Evaluates a simulation transcript against a scoring rubric.

YOU MUST IMPLEMENT: The Scorer class with the score() method.

Scoring Algorithm:

For each rubric item:

1. CONTRAINDICATED items (category == "contraindicated"):
   - If the action appears in the transcript: add penalty = risk_weight
   - No credit is awarded (max_credit is 0)

2. REQUIRED / RECOMMENDED items:
   - Find the earliest timestamp when the action was performed
   - If action was NOT performed: credit = 0
   - If action was performed, check prerequisites:
     * Each prerequisite must appear in the transcript at a STRICTLY earlier
       timestamp (prereq_time < action_time)
     * If any prerequisite is not met: credit = 0
   - If prerequisites are met, calculate time-based credit:
     * If action_time <= time_window_end: credit = max_credit (full credit)
     * If action_time > time_window_end:
       credit = max(0, max_credit - (action_time - time_window_end) * decay_per_minute)

Action matching in transcript:
- For rubric actions starting with "change_location:":
  Look for transcript entries with action_type == "change_location"
  where details["location"] matches the part after the colon
- For all other rubric actions:
  Look for transcript entries with action_type == "order"
  where details["canonical_name"] matches the rubric action

Final score = max(0, min(max_score, sum(credits) - sum(penalties)))
"""


class Scorer:
    def __init__(self, rubric: dict):
        """
        Initialize the scorer with a rubric.

        Args:
            rubric: Dict with keys:
                - max_score (float): Maximum possible score
                - items (list[dict]): Rubric items, each with:
                    - action (str)
                    - category (str): "required" | "recommended" | "contraindicated"
                    - max_credit (float)
                    - time_window_start (int)
                    - time_window_end (int)
                    - prerequisites (list[str])
                    - decay_per_minute (float)
                    - risk_weight (float)
        """
        raise NotImplementedError("Implement Scorer.__init__")

    def score(self, transcript: list[dict]) -> dict:
        """
        Score a simulation transcript against the rubric.

        Args:
            transcript: List of transcript entries, each with:
                - action_type: "order" | "advance_clock" | "change_location"
                - timestamp: int
                - details: dict (with "canonical_name" for orders,
                  "location" for location changes)

        Returns:
            {
                "total_score": float,
                "category_scores": dict[str, float],  # percentage per category
                "item_details": list[dict],  # per-item breakdown
                "penalties": list[dict]  # contraindicated action penalties
            }

            item_details entries:
            {
                "action": str,
                "credit": float,
                "max_credit": float,
                "reason": str
            }

            penalties entries:
            {
                "action": str,
                "penalty": float,
                "reason": str
            }
        """
        raise NotImplementedError("Implement Scorer.score")
