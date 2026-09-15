"""
Frost Number Calculator - Reference Implementation
Adapted from the permamodel package (Nelson & Outcalt, 1983).

Computes the air frost number from monthly temperature extremes
using degree-day indices derived from the annual temperature cycle.
"""

import numpy as np


class FrostNumberCalculator:
    """Compute the reduced air frost number from temperature data.

    The frost number quantifies the balance between freezing and
    thawing at a site. It ranges from 0 (no freezing) to 1
    (permanently frozen).

    The calculation assumes a sinusoidal annual temperature cycle
    characterized by mean temperature T_avg and amplitude T_amp.

    Degree-day indices are computed by integrating the positive and
    negative portions of the temperature curve over one year.

    The frost number is:
        F = sqrt(DDF) / (sqrt(DDF) + sqrt(DDT))

    where DDF = degree-days of freezing and DDT = degree-days of
    thawing.

    Parameters can be specified as:
      - T_cold, T_hot (coldest and warmest monthly means), or
      - T_avg, T_amp (mean and half-amplitude)

    Relationship: T_avg = (T_hot + T_cold) / 2
                  T_amp = (T_hot - T_cold) / 2
    """

    @staticmethod
    def from_monthly_extremes(T_cold, T_hot):
        """Compute frost number from coldest and warmest monthly means.

        Parameters
        ----------
        T_cold : float
            Coldest monthly mean temperature [degC]
        T_hot : float
            Warmest monthly mean temperature [degC]

        Returns
        -------
        float
            Air frost number in [0, 1]
        """
        T_avg = (T_hot + T_cold) / 2.0
        T_amp = (T_hot - T_cold) / 2.0
        return FrostNumberCalculator._compute(T_avg, T_amp)

    @staticmethod
    def from_mean_and_amplitude(T_avg, T_amp):
        """Compute frost number from mean temperature and amplitude.

        Parameters
        ----------
        T_avg : float
            Mean annual temperature [degC]
        T_amp : float
            Half-amplitude of annual cycle [degC]

        Returns
        -------
        float
            Air frost number in [0, 1]
        """
        return FrostNumberCalculator._compute(T_avg, T_amp)

    @staticmethod
    def _compute(T_avg, T_amp):
        """Core frost number calculation.

        For a sinusoidal annual cycle T(t) = T_avg + T_amp * cos(wt),
        the degree-day indices are found by integrating the positive
        and negative parts of T(t) over one year.

        Edge cases:
        - If T_avg + T_amp <= 0: always frozen, F = 1.0
        - If T_avg - T_amp >= 0: never frozen, F = 0.0
        - Otherwise: mixed regime using analytical integration
        """
        if T_amp <= 0:
            return 1.0 if T_avg < 0 else 0.0

        # Always-frozen case
        if T_avg + T_amp <= 0:
            return 1.0

        # Never-frozen case
        if T_avg - T_amp >= 0:
            return 0.0

        # Mixed regime: compute degree-day indices analytically
        # Beta is the half-angle of the thawing season
        Beta = np.arccos(-T_avg / T_amp)

        # Mean temperatures during thawing and freezing seasons
        T_summer = T_avg + T_amp * np.sin(Beta) / Beta
        T_winter = T_avg - T_amp * np.sin(Beta) / (np.pi - Beta)

        # Season lengths in days
        L_summer = 365.0 * Beta / np.pi
        L_winter = 365.0 - L_summer

        # Degree-day indices
        DDT = T_summer * L_summer
        DDF = -T_winter * L_winter

        if DDF <= 0:
            return 0.0
        if DDT <= 0:
            return 1.0

        return np.sqrt(DDF) / (np.sqrt(DDF) + np.sqrt(DDT))
