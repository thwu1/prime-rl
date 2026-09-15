"""Option payoff functions for European, Asian, and barrier contracts."""
import math


def european_call(path, K, r, T):
    """Discounted European call payoff: e^{-rT} max(S_T - K, 0)."""
    S_T = path[-1]
    return math.exp(-r * T) * max(S_T - K, 0.0)


def european_put(path, K, r, T):
    """Discounted European put payoff: e^{-rT} max(K - S_T, 0)."""
    S_T = path[-1]
    return math.exp(-r * T) * max(K - S_T, 0.0)


def asian_call(path, K, r, T, S0):
    """Discounted arithmetic-average Asian call payoff.

    The arithmetic average is taken over the monitoring prices
    (the discrete stock prices along the path).
    Payoff = e^{-rT} max(A - K, 0)
    """
    avg = (S0 + sum(path)) / (len(path) + 1)
    return math.exp(-r * T) * max(avg - K, 0.0)


def barrier_up_out_call(path, K, r, T, S0, barrier):
    """Discounted up-and-out barrier call payoff with discrete monitoring.

    The option pays max(S_T - K, 0) * e^{-rT} if the stock never touches
    or exceeds the barrier during monitoring. Returns 0 if breached.

    TODO: Implement this function.
    """
    raise NotImplementedError("barrier_up_out_call is not yet implemented")
