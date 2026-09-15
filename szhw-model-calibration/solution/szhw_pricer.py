
"""SZHW (Schoebel-Zhu-Hull-White) model pricer.

Implements the semi-analytical characteristic function for the SZHW
stochastic volatility + stochastic interest rate model and prices
European call options via the COS (Fourier cosine expansion) method.

Reference: Grzelak & Oosterlee, "On the Heston Model with Stochastic
Interest Rates", SIAM J. Financial Math., 2(1), 255-286 (2011).
"""
import numpy as np

I_UNIT = complex(0.0, 1.0)

# Handle numpy API change: trapz -> trapezoid in numpy >= 2.0
_trapz = getattr(np, 'trapezoid', None) or np.trapz


def compute_call_prices(S0, K, T, P0T, kappa, Rxr, lambd, eta,
                        gamma, sigmabar, Rrsigma, Rxsigma, sigma0):
    """Price European calls under the SZHW model via COS method.

    Parameters
    ----------
    S0 : float - spot price
    K : list[float] - strike prices
    T : float - time to maturity
    P0T : float - zero-coupon bond price P(0,T)
    kappa : float - mean reversion speed of volatility
    Rxr : float - correlation(stock, rate)
    lambd : float - mean reversion speed of interest rate
    eta : float - volatility of interest rate
    gamma : float - vol-of-vol
    sigmabar : float - long-run volatility level
    Rrsigma : float - correlation(rate, volatility)
    Rxsigma : float - correlation(stock, volatility)
    sigma0 : float - initial volatility

    Returns
    -------
    list[float] - call option prices for each strike
    """

    # ------------------------------------------------------------------
    # SZHW characteristic function sub-components
    # ------------------------------------------------------------------
    def C_func(u, tau):
        """Hull-White rate component."""
        return (1.0 / lambd) * (I_UNIT * u - 1.0) * (1.0 - np.exp(-lambd * tau))

    def D_func(u, tau):
        """Riccati ODE solution for variance component."""
        a_0 = -0.5 * u * (I_UNIT + u)
        a_1 = 2.0 * (gamma * Rxsigma * I_UNIT * u - kappa)
        a_2 = 2.0 * gamma * gamma
        d = np.sqrt(a_1 * a_1 - 4.0 * a_0 * a_2)
        g = (-a_1 - d) / (-a_1 + d)
        return ((-a_1 - d)
                / (2.0 * a_2 * (1.0 - g * np.exp(-d * tau)))
                * (1.0 - np.exp(-d * tau)))

    def E_func(u, tau):
        """Mixed rate-volatility interaction term."""
        a_0 = -0.5 * u * (I_UNIT + u)
        a_1 = 2.0 * (gamma * Rxsigma * I_UNIT * u - kappa)
        a_2 = 2.0 * gamma * gamma
        d = np.sqrt(a_1 * a_1 - 4.0 * a_0 * a_2)
        g = (-a_1 - d) / (-a_1 + d)
        c_1 = gamma * Rxsigma * I_UNIT * u - kappa - 0.5 * (a_1 + d)

        f_1 = (1.0 / c_1 * (1.0 - np.exp(-c_1 * tau))
               + 1.0 / (c_1 + d) * (np.exp(-(c_1 + d) * tau) - 1.0))
        f_2 = (1.0 / c_1 * (1.0 - np.exp(-c_1 * tau))
               + 1.0 / (c_1 + lambd) * (np.exp(-(c_1 + lambd) * tau) - 1.0))
        f_3 = ((np.exp(-(c_1 + d) * tau) - 1.0) / (c_1 + d)
               + (1.0 - np.exp(-(c_1 + d + lambd) * tau)) / (c_1 + d + lambd))
        f_4 = (1.0 / c_1 - 1.0 / (c_1 + d)
               - 1.0 / (c_1 + lambd) + 1.0 / (c_1 + d + lambd))
        f_5 = (np.exp(-(c_1 + d + lambd) * tau)
               * (np.exp(lambd * tau) * (1.0 / (c_1 + d)
                                         - np.exp(d * tau) / c_1)
                  + np.exp(d * tau) / (c_1 + lambd)
                  - 1.0 / (c_1 + d + lambd)))

        I_1 = kappa * sigmabar / a_2 * (-a_1 - d) * f_1
        I_2 = (eta * Rxr * I_UNIT * u * (I_UNIT * u - 1.0)
               / lambd * (f_2 + g * f_3))
        I_3 = (-Rrsigma * eta * gamma / (lambd * a_2)
               * (a_1 + d) * (I_UNIT * u - 1.0) * (f_4 + f_5))

        return (np.exp(c_1 * tau)
                / (1.0 - g * np.exp(-d * tau))
                * (I_1 + I_2 + I_3))

    def A_func(u, tau):
        """Integrated correction term (numerical quadrature)."""
        a_0 = -0.5 * u * (I_UNIT + u)
        a_1 = 2.0 * (gamma * Rxsigma * I_UNIT * u - kappa)
        a_2 = 2.0 * gamma * gamma
        d = np.sqrt(a_1 * a_1 - 4.0 * a_0 * a_2)
        g = (-a_1 - d) / (-a_1 + d)

        f_6 = (eta ** 2 / (4.0 * lambd ** 3)
               * (I_UNIT + u) ** 2
               * (3.0 + np.exp(-2.0 * lambd * tau)
                  - 4.0 * np.exp(-lambd * tau)
                  - 2.0 * lambd * tau))
        A_1 = (0.25 * ((-a_1 - d) * tau
                        - 2.0 * np.log((1.0 - g * np.exp(-d * tau))
                                       / (1.0 - g)))
               + f_6)

        N_int = 50
        z1 = np.linspace(0, tau, N_int)

        E_v = E_func(u, z1)
        C_v = C_func(u, z1)
        integrand = ((kappa * sigmabar
                      + 0.5 * gamma ** 2 * E_v
                      + gamma * eta * Rrsigma * C_v)
                     * E_v)

        value1 = _trapz(np.real(integrand), z1).reshape(u.size, 1)
        value2 = _trapz(np.imag(integrand), z1).reshape(u.size, 1)
        value = value1 + value2 * I_UNIT

        return value + A_1

    def szhw_cf(u):
        """Full SZHW characteristic function."""
        v_D = D_func(u, T)
        v_E = E_func(u, T)
        v_A = A_func(u, T)
        v_0 = sigma0 * sigma0

        hlp = (eta ** 2 / (2.0 * lambd ** 2)
               * (T + 2.0 / lambd * (np.exp(-lambd * T) - 1.0)
                  - 1.0 / (2.0 * lambd) * (np.exp(-2.0 * lambd * T) - 1.0)))
        correction = (I_UNIT * u - 1.0) * (np.log(1.0 / P0T) + hlp)

        cf = np.exp(v_0 * v_D + sigma0 * v_E + v_A + correction)
        return cf.tolist()

    # ------------------------------------------------------------------
    # COS method
    # ------------------------------------------------------------------
    K_arr = np.array(K).reshape([len(K), 1])
    x0 = np.log(S0 / K_arr)

    N_cos = 1000
    L = 15
    a = -L * np.sqrt(T)
    b = L * np.sqrt(T)

    k = np.linspace(0, N_cos - 1, N_cos).reshape([N_cos, 1])
    u = k * np.pi / (b - a)

    # Put coefficients (c=a, d=0)
    c_coef, d_coef = a, 0.0
    psi = (np.sin(k * np.pi * (d_coef - a) / (b - a))
           - np.sin(k * np.pi * (c_coef - a) / (b - a)))
    psi[1:] = psi[1:] * (b - a) / (k[1:] * np.pi)
    psi[0] = d_coef - c_coef

    chi = 1.0 / (1.0 + np.power(k * np.pi / (b - a), 2.0))
    expr1 = (np.cos(k * np.pi * (d_coef - a) / (b - a)) * np.exp(d_coef)
             - np.cos(k * np.pi * (c_coef - a) / (b - a)) * np.exp(c_coef))
    expr2 = (k * np.pi / (b - a)
             * np.sin(k * np.pi * (d_coef - a) / (b - a))
             - k * np.pi / (b - a)
             * np.sin(k * np.pi * (c_coef - a) / (b - a)) * np.exp(c_coef))
    chi = chi * (expr1 + expr2)

    H_k = 2.0 / (b - a) * (-chi + psi)

    mat = np.exp(I_UNIT * np.outer((x0 - a), u))
    cf_vals = np.array(szhw_cf(u))
    temp = cf_vals * H_k
    temp[0] = 0.5 * temp[0]
    put_value = K_arr * np.real(mat.dot(temp))
    call_value = put_value + S0 - K_arr * P0T

    return [float(v) for v in call_value.flatten()]
