
"""HfO2 Bilayer RRAM custom device model for CrossSim.

Programming error : quadratic state-dependent sigma
Read noise        : sqrt state-dependent sigma
Drift             : power-law with state-dependent exponent (deterministic)

All formulas operate in real conductance (microSiemens) and are converted
back to CrossSim's normalized conductance system before returning.
"""

from simulator.devices.idevice import EmptyDevice
from simulator.backend import ComputeBackend

xp = ComputeBackend()


class HfO2BilayerRRAM(EmptyDevice):
    """HfO2 bilayer RRAM device with state-dependent analog errors."""

    # Programming-error coefficients (G in uS)
    _A2 = 0.0008   # uS^{-1}
    _A1 = -0.07
    _A0 = 3.5       # uS

    # Read-noise coefficients (G in uS)
    _C1 = 0.3       # uS^{1/2}
    _C0 = 0.5       # uS

    # Drift parameters
    _TAU = 5.0      # days
    _NU0 = 0.01
    _NU1 = 0.04

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Compute real conductance bounds from device parameters
        self.Gmax_real = 1.0 / self.device_params.Rmin          # Siemens
        self.Gmin_real = 1.0 / self.device_params.Rmax          # Siemens
        self.Grange_real = self.Gmax_real - self.Gmin_real

    # ---- internal helpers ------------------------------------------------

    def _to_real_uS(self, normed):
        """Normalized conductance -> real conductance in micro-Siemens."""
        G_S = (self.Gmin_real
               + self.Grange_real
               * (normed - self.Gmin_norm) / self.Grange_norm)
        return G_S * 1.0e6

    def _to_real_S(self, normed):
        """Normalized conductance -> real conductance in Siemens."""
        return (self.Gmin_real
                + self.Grange_real
                * (normed - self.Gmin_norm) / self.Grange_norm)

    def _to_norm(self, G_S):
        """Real conductance (S) -> normalized conductance."""
        return (self.Gmin_norm
                + self.Grange_norm
                * (G_S - self.Gmin_real) / self.Grange_real)

    # ---- public interface ------------------------------------------------

    def programming_error(self, input_):
        """Quadratic state-dependent programming error."""
        G_uS = self._to_real_uS(input_)

        sigma_uS = xp.maximum(
            self._A2 * G_uS ** 2 + self._A1 * G_uS + self._A0, 0.0
        )
        # Convert sigma from physical (uS -> S) to normalized weight units
        sigma_W = (sigma_uS * 1.0e-6) / self.Grange_real

        if sigma_W.any():
            randMat = xp.random.normal(
                scale=self.Grange_norm, size=input_.shape
            ).astype(input_.dtype)
            input_ = input_ + sigma_W * randMat

        return input_

    def read_noise(self, input_):
        """Sqrt state-dependent read noise (applied every MVM)."""
        G_uS = self._to_real_uS(input_)

        sigma_uS = xp.maximum(
            self._C1 * xp.sqrt(xp.maximum(G_uS, 0.0)) + self._C0, 0.0
        )
        sigma_W = (sigma_uS * 1.0e-6) / self.Grange_real

        if sigma_W.any():
            randMat = xp.random.normal(
                scale=self.Grange_norm, size=input_.shape
            ).astype(input_.dtype)
            input_ = input_ + sigma_W * randMat

        return input_

    def read_noise_variance(self, input_):
        """Variance of read noise in normalized units (for lumped model)."""
        G_uS = self._to_real_uS(input_)
        sigma_uS = self._C1 * xp.sqrt(xp.maximum(G_uS, 0.0)) + self._C0
        sigma_W = (sigma_uS * 1.0e-6) / self.Grange_real
        return sigma_W ** 2

    def drift_error(self, input_, time):
        """Power-law drift with state-dependent exponent (deterministic)."""
        if time <= 0:
            return input_

        G_S = self._to_real_S(input_)

        nu = self._NU0 + self._NU1 * (G_S / self.Gmax_real)
        G_drifted = G_S * xp.power(1.0 + time / self._TAU, -nu)

        return self._to_norm(G_drifted)
