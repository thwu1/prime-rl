"""
Scorer - Solution Implementation

Rubric-based transcript evaluation with time-windowed credit,
prerequisite sequencing, and contraindication penalties.
"""


class Scorer:
    def __init__(self, rubric: dict):
        self.rubric = rubric
        self.items = rubric.get("items", [])
        self.max_score = rubric.get("max_score", 100)

    def _find_action_time(self, transcript: list[dict], action: str):
        """Find the earliest timestamp when an action was performed."""
        if action.startswith("change_location:"):
            target_location = action.split(":", 1)[1]
            for entry in transcript:
                if entry["action_type"] == "change_location":
                    if entry["details"].get("location") == target_location:
                        return entry["timestamp"]
            return None
        else:
            for entry in transcript:
                if entry["action_type"] == "order":
                    if entry["details"].get("canonical_name") == action:
                        return entry["timestamp"]
            return None

    def _check_prerequisites(
        self, transcript: list[dict], prerequisites: list[str], action_time: int
    ) -> tuple:
        """
        Check if all prerequisites were performed strictly before action_time.
        Returns (met: bool, failed_prereq: str or None).
        """
        for prereq in prerequisites:
            prereq_time = self._find_action_time(transcript, prereq)
            if prereq_time is None or prereq_time >= action_time:
                return False, prereq
        return True, None

    def score(self, transcript: list[dict]) -> dict:
        item_details = []
        penalties = []
        total_credit = 0.0
        total_penalty = 0.0

        for item in self.items:
            action = item["action"]
            category = item["category"]
            max_credit = item["max_credit"]
            window_end = item["time_window_end"]
            prerequisites = item.get("prerequisites", [])
            decay = item.get("decay_per_minute", 0.0)
            risk_weight = item.get("risk_weight", 0.0)

            action_time = self._find_action_time(transcript, action)

            # Handle contraindicated actions
            if category == "contraindicated":
                if action_time is not None:
                    penalties.append(
                        {
                            "action": action,
                            "penalty": risk_weight,
                            "reason": (
                                f"Contraindicated action performed at t={action_time}"
                            ),
                        }
                    )
                    total_penalty += risk_weight
                item_details.append(
                    {
                        "action": action,
                        "credit": 0.0,
                        "max_credit": 0.0,
                        "reason": (
                            "Contraindicated"
                            if action_time is None
                            else f"Contraindicated - penalty {risk_weight}"
                        ),
                    }
                )
                continue

            # Handle required/recommended actions
            if action_time is None:
                item_details.append(
                    {
                        "action": action,
                        "credit": 0.0,
                        "max_credit": max_credit,
                        "reason": "Action not performed",
                    }
                )
                continue

            # Check prerequisites
            prereqs_met, failed_prereq = self._check_prerequisites(
                transcript, prerequisites, action_time
            )

            if not prereqs_met:
                item_details.append(
                    {
                        "action": action,
                        "credit": 0.0,
                        "max_credit": max_credit,
                        "reason": (
                            f"Prerequisite not met: {failed_prereq} "
                            f"must be performed before {action}"
                        ),
                    }
                )
                continue

            # Calculate time-based credit
            if action_time <= window_end:
                credit = max_credit
                reason = (
                    f"Performed at t={action_time}, "
                    f"within window [0, {window_end}]"
                )
            else:
                delay = action_time - window_end
                credit = max(0.0, max_credit - delay * decay)
                reason = (
                    f"Performed at t={action_time}, "
                    f"{delay}min past window end. Decay applied."
                )

            credit = round(credit, 2)
            total_credit += credit

            item_details.append(
                {
                    "action": action,
                    "credit": credit,
                    "max_credit": max_credit,
                    "reason": reason,
                }
            )

        # Calculate final score
        total_score = max(0.0, min(float(self.max_score), total_credit - total_penalty))

        # Calculate category scores (percentage per category)
        category_credits = {}
        for detail in item_details:
            cat = next(
                (
                    it["category"]
                    for it in self.items
                    if it["action"] == detail["action"]
                ),
                "unknown",
            )
            if cat not in category_credits:
                category_credits[cat] = {"earned": 0.0, "possible": 0.0}
            category_credits[cat]["earned"] += detail["credit"]
            category_credits[cat]["possible"] += detail["max_credit"]

        category_scores = {}
        for cat, vals in category_credits.items():
            if vals["possible"] > 0:
                category_scores[cat] = round(
                    vals["earned"] / vals["possible"] * 100, 1
                )
            else:
                category_scores[cat] = 100.0

        return {
            "total_score": round(total_score, 2),
            "category_scores": category_scores,
            "item_details": item_details,
            "penalties": penalties,
        }
