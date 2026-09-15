"""
Pairwise comparison model for forecaster skill estimation.
Estimates latent skill parameters by comparing prediction accuracy
between pairs of forecasters on shared events.
"""
from collections import defaultdict


class SkillEstimator:
    """
    Estimates forecaster skill parameters from pairwise accuracy comparisons.

    For each event where two forecasters both made predictions, the one
    whose predicted probability was closer to the actual outcome wins
    the comparison. Ties (equal absolute error) are split equally (0.5 each).

    Skill parameters are estimated via iterative proportional fitting:
        theta_i = W_i / sum_j( n_ij / (theta_i + theta_j) )

    where W_i is total wins for forecaster i, and n_ij is total number
    of comparisons between i and j. After each iteration, all parameters
    are normalized by dividing by their mean to maintain identifiability.

    Convergence criterion: max absolute parameter change < tolerance,
    or maximum number of iterations reached.
    """

    def __init__(self, max_iterations=1000, tolerance=1e-8):
        self.max_iterations = max_iterations
        self.tolerance = tolerance

    def build_comparisons(self, event_predictions, event_outcomes):
        """
        Build pairwise win counts from per-event prediction data.

        Args:
            event_predictions: dict mapping event_id to list of
                (forecaster_id, predicted_probability) tuples
            event_outcomes: dict mapping event_id to actual outcome (0 or 1)

        Returns:
            (win_counts, forecaster_ids) where:
                win_counts: dict of (fid_a, fid_b) -> number of wins of a over b
                forecaster_ids: sorted list of all forecaster IDs
        """
        wins = defaultdict(float)

        for eid, preds in event_predictions.items():
            outcome = event_outcomes.get(eid)
            if outcome is None:
                continue
            for a_idx in range(len(preds)):
                for b_idx in range(a_idx + 1, len(preds)):
                    fid_a, prob_a = preds[a_idx]
                    fid_b, prob_b = preds[b_idx]
                    err_a = abs(prob_a - outcome)
                    err_b = abs(prob_b - outcome)
                    if err_a < err_b:
                        wins[(fid_a, fid_b)] += 1
                    elif err_b < err_a:
                        wins[(fid_b, fid_a)] += 1
                    else:
                        wins[(fid_a, fid_b)] += 0.5
                        wins[(fid_b, fid_a)] += 0.5

        forecaster_ids = sorted(set(
            fid for pair in wins.keys() for fid in pair
        ))
        return dict(wins), forecaster_ids

    def estimate_skills(self, win_counts, forecaster_ids):
        """
        Estimate skill parameters via iterative fitting.

        Args:
            win_counts: dict of (fid_a, fid_b) -> count of a's wins over b
            forecaster_ids: sorted list of forecaster IDs

        Returns:
            dict mapping forecaster_id to estimated skill parameter (float)
        """
        n = len(forecaster_ids)
        fid_to_idx = {fid: i for i, fid in enumerate(forecaster_ids)}

        win_matrix = [[0.0] * n for _ in range(n)]
        for (fa, fb), count in win_counts.items():
            if fa in fid_to_idx and fb in fid_to_idx:
                win_matrix[fid_to_idx[fa]][fid_to_idx[fb]] = count

        total_comp = [[win_matrix[i][j] + win_matrix[j][i]
                       for j in range(n)] for i in range(n)]
        total_wins = [sum(win_matrix[i]) for i in range(n)]

        theta = [1.0] * n

        for _ in range(self.max_iterations):
            theta_old = theta[:]
            for i in range(n):
                denom = 0.0
                for j in range(n):
                    if i != j and total_comp[i][j] > 0:
                        denom += total_comp[i][j] / (theta_old[i] + theta_old[j])
                if denom > 0 and total_wins[i] > 0:
                    theta[i] = total_wins[i] / denom
                else:
                    theta[i] = theta_old[i]

            # Normalize by mean
            mean_theta = sum(theta) / n
            theta = [t / mean_theta for t in theta]

            max_change = max(abs(theta[i] - theta_old[i]) for i in range(n))
            if max_change < self.tolerance:
                break

        return {forecaster_ids[i]: theta[i] for i in range(n)}
