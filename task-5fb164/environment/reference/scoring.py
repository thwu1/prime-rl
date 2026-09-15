"""
Scoring models for prediction market forecaster evaluation.
Each scorer takes cleaned, pre-processed prediction data and returns
per-forecaster scores. Data quality checks and deduplication are the
caller's responsibility.
"""


class CalibrationScorer:
    """
    Measures forecast accuracy via quadratic proper scoring rule.
    Score = 1 - mean(squared prediction error) across all events a
    forecaster predicted. Higher scores indicate better calibration.
    """

    def score_forecasters(self, forecaster_predictions):
        """
        Args:
            forecaster_predictions: dict mapping forecaster_id to list of
                (predicted_probability, actual_outcome) tuples.
                actual_outcome is 0 or 1.
        Returns:
            dict mapping forecaster_id to calibration score (float)
        """
        scores = {}
        for fid, preds in forecaster_predictions.items():
            if not preds:
                continue
            sq_errors = [(p - o) ** 2 for p, o in preds]
            scores[fid] = 1.0 - sum(sq_errors) / len(sq_errors)
        return scores


class RiskNeutralTrader:
    """
    Simulates a risk-neutral trader who invests their entire unit budget
    on whichever contract side (YES or NO) offers positive expected value,
    choosing the higher-EV side when both are positive.

    Expected value of going all-in on YES:  prob / yes_price - 1
    Expected value of going all-in on NO:   (1-prob) / no_price - 1

    If neither side has positive EV, the trader holds cash (return = 0).

    Realized return when betting on YES:
        outcome=1 (win):  1/yes_price - 1
        outcome=0 (lose): -1 (total loss of budget)
    Analogously for NO side.

    Score = mean realized return across all traded events.
    """

    def score_forecasters(self, forecaster_trades):
        """
        Args:
            forecaster_trades: dict mapping forecaster_id to list of
                (predicted_prob, yes_price, no_price, actual_outcome) tuples
        Returns:
            dict mapping forecaster_id to average realized return (float)
        """
        scores = {}
        for fid, trades in forecaster_trades.items():
            if not trades:
                continue
            returns = []
            for prob, c_yes, c_no, outcome in trades:
                ev_yes = prob / c_yes - 1.0
                ev_no = (1.0 - prob) / c_no - 1.0
                if ev_yes > 0 and ev_yes >= ev_no:
                    ret = (1.0 / c_yes - 1.0) if outcome == 1 else -1.0
                elif ev_no > 0:
                    ret = (1.0 / c_no - 1.0) if outcome == 0 else -1.0
                else:
                    ret = 0.0
                returns.append(ret)
            scores[fid] = sum(returns) / len(returns)
        return scores


class KellyTrader:
    """
    Simulates a trader using the Kelly criterion (log-utility, CRRA gamma=1)
    for fractional bet sizing.

    For YES side: fraction f = (prob - yes_price) / (1 - yes_price),
                  clamped to [0, 1]
    For NO side:  fraction g = ((1-prob) - no_price) / (1 - no_price),
                  clamped to [0, 1]

    The trader bets on whichever side has the larger positive fraction.
    If both fractions are zero or negative, the trader holds cash.

    Wealth after betting fraction f on YES:
        outcome=1: 1 + f * (1 - yes_price) / yes_price
        outcome=0: 1 - f

    Return = wealth - 1.
    Score = mean return across all events.
    """

    def score_forecasters(self, forecaster_trades):
        """
        Args:
            forecaster_trades: dict mapping forecaster_id to list of
                (predicted_prob, yes_price, no_price, actual_outcome) tuples
        Returns:
            dict mapping forecaster_id to average kelly return (float)
        """
        scores = {}
        for fid, trades in forecaster_trades.items():
            if not trades:
                continue
            returns = []
            for prob, c_yes, c_no, outcome in trades:
                f_yes = max(0.0, min(1.0,
                    (prob - c_yes) / (1.0 - c_yes) if c_yes < 1 else 0.0))
                f_no = max(0.0, min(1.0,
                    ((1.0 - prob) - c_no) / (1.0 - c_no) if c_no < 1 else 0.0))

                if f_yes > 0 and f_yes >= f_no:
                    if outcome == 1:
                        wealth = 1.0 + f_yes * (1.0 - c_yes) / c_yes
                    else:
                        wealth = 1.0 - f_yes
                    ret = wealth - 1.0
                elif f_no > 0:
                    if outcome == 0:
                        wealth = 1.0 + f_no * (1.0 - c_no) / c_no
                    else:
                        wealth = 1.0 - f_no
                    ret = wealth - 1.0
                else:
                    ret = 0.0
                returns.append(ret)
            scores[fid] = sum(returns) / len(returns)
        return scores


class CRRATrader:
    """
    Simulates a trader using CRRA (Constant Relative Risk Aversion) utility
    optimization for bet sizing. This generalizes both risk-neutral (gamma=0)
    and Kelly/log-utility (gamma=1) trading into a single parametric family.

    The CRRA utility function is:
        U(W) = W^(1-gamma) / (1-gamma)    for gamma != 1
        U(W) = ln(W)                       for gamma = 1

    The parameter gamma controls risk aversion:
      - gamma = 0: risk neutral (all-in on positive-EV side)
      - gamma = 0.5: moderate risk aversion (power utility sqrt)
      - gamma = 1: log utility (Kelly criterion)

    For a YES contract at price c with subjective probability p:
        The trader maximizes E[U(W)] = p*U(1+f*R) + (1-p)*U(1-f)
        where R = 1/c - 1 and f is the bet fraction in [0, 1).

    The optimal fraction satisfies the first-order condition:
        p * R * (1+f*R)^(-gamma) = (1-p) * (1-f)^(-gamma)

    For gamma = 0.5, squaring the FOC and solving yields:
        f = [p^2 * R^2 - (1-p)^2] / [R * (p^2 * R + (1-p)^2)]
        clamped to [0, 1], where f > 0 iff p > c.

    The trader bets on whichever side (YES or NO) yields the larger
    positive optimal fraction. If both are zero, holds cash.

    Score = mean realized return across all events.
    """

    def __init__(self, gamma=0.5):
        self.gamma = gamma

    def optimal_fraction(self, prob, price):
        """
        Compute CRRA-optimal bet fraction for a binary contract.

        Args:
            prob: subjective probability of the contract paying out
            price: market price of the contract

        Returns:
            Optimal fraction of wealth to bet, in [0, 1]
        """
        if price >= 1.0 or price <= 0.0:
            return 0.0
        R = 1.0 / price - 1.0
        if R <= 0:
            return 0.0
        p = prob
        q = 1.0 - prob
        if self.gamma == 0.5:
            num = p ** 2 * R ** 2 - q ** 2
            den = R * (p ** 2 * R + q ** 2)
            if den <= 0:
                return 0.0
            f = num / den
            return max(0.0, min(1.0, f))
        elif self.gamma == 1.0:
            # Kelly criterion
            return max(0.0, min(1.0, (prob - price) / (1.0 - price)))
        elif self.gamma == 0.0:
            # Risk neutral: all-in if positive EV
            return 1.0 if prob > price else 0.0
        else:
            raise NotImplementedError(
                "General gamma requires numerical optimization")

    def score_forecasters(self, forecaster_trades):
        """
        Args:
            forecaster_trades: dict mapping forecaster_id to list of
                (predicted_prob, yes_price, no_price, actual_outcome) tuples
        Returns:
            dict mapping forecaster_id to average CRRA return (float)
        """
        scores = {}
        for fid, trades in forecaster_trades.items():
            if not trades:
                continue
            returns = []
            for prob, c_yes, c_no, outcome in trades:
                f_yes = self.optimal_fraction(prob, c_yes)
                f_no = self.optimal_fraction(1.0 - prob, c_no)

                if f_yes > 0 and f_yes >= f_no:
                    if outcome == 1:
                        ret = f_yes * (1.0 / c_yes - 1.0)
                    else:
                        ret = -f_yes
                elif f_no > 0:
                    if outcome == 0:
                        ret = f_no * (1.0 / c_no - 1.0)
                    else:
                        ret = -f_no
                else:
                    ret = 0.0
                returns.append(ret)
            scores[fid] = sum(returns) / len(returns)
        return scores
