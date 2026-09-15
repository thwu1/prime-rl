import numpy as np


def solver(Vx0, density0, pressure0, t_coordinate, eta, zeta):
    """Solves the 1D compressible Navier-Stokes equations using forward Euler
    time integration with central finite differences on a periodic domain.

    Args:
        Vx0 (np.ndarray): Initial velocity field [batch_size, N].
        density0 (np.ndarray): Initial density field [batch_size, N].
        pressure0 (np.ndarray): Initial pressure field [batch_size, N].
        t_coordinate (np.ndarray): Output time coordinates [T+1], starting at t=0.
        eta (float): Shear viscosity coefficient.
        zeta (float): Bulk viscosity coefficient.

    Returns:
        Tuple of (Vx_pred, density_pred, pressure_pred), each [batch_size, T+1, N].
    """
    batch_size, N = Vx0.shape
    T = len(t_coordinate) - 1
    dx = 2.0 / (N - 1)

    Vx_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    density_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    pressure_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)

    Vx_pred[:, 0] = Vx0
    density_pred[:, 0] = density0
    pressure_pred[:, 0] = pressure0

    GAMMA = 5.0 / 3.0
    HYPERBOLIC_SAFETY = 0.1
    MIN_DT = 5e-7
    MAX_DT = 1e-4
    ARTIFICIAL_VISCOSITY_COEFF = 1.5

    def periodic_pad(x):
        """Pad with correct periodic ghost cells for vertex-centered grid.
        Endpoints coincide, so ghost cells use the second-to-last and second
        elements rather than the last and first.
        """
        return np.concatenate([x[:, -2:-1], x, x[:, 1:2]], axis=1)

    def compute_rhs(Vx, density, pressure):
        """Compute right-hand side of the CNS1D conservation laws."""
        Vx_pad = periodic_pad(Vx)
        density_pad = periodic_pad(density)
        pressure_pad = periodic_pad(pressure)

        # First and second spatial derivatives via central differences
        dv_dx = (Vx_pad[:, 2:] - Vx_pad[:, :-2]) / (2 * dx)
        d2v_dx2 = (Vx_pad[:, 2:] - 2 * Vx + Vx_pad[:, :-2]) / (dx ** 2)

        # --- Continuity equation: d(rho)/dt = -d(rho*v)/dx ---
        rho_v = density * Vx
        rho_v_pad = periodic_pad(rho_v)
        drho_v_dx = (rho_v_pad[:, 2:] - rho_v_pad[:, :-2]) / (2 * dx)
        drho_dt = -drho_v_dx

        # --- Momentum equation ---
        # Pressure gradient
        pressure_grad = (
            (pressure_pad[:, 2:] - pressure_pad[:, :-2]) / (2 * dx)
        )
        safe_density = np.clip(density, 1e-4, None)

        # rho*(dv/dt + v*dv/dx) = -dp/dx + viscous terms
        # => dv/dt = -v*dv/dx - (1/rho)*dp/dx + (1/rho)*viscous
        # For the diffusion coefficient: eta*d2v/dx2 + (zeta + eta/3)*d2v/dx2
        #   = (eta + zeta + eta/3)*d2v/dx2
        dv_dt = (
            -Vx * dv_dx
            - pressure_grad / safe_density
            + (eta + zeta + eta / 3) * d2v_dx2
        )

        # Artificial viscosity for numerical stabilization
        div_v = dv_dx
        art_visc = (
            ARTIFICIAL_VISCOSITY_COEFF * density * dx ** 2
            * np.abs(div_v) * div_v
        )
        dv_dt = dv_dt + art_visc
        dv_dt = np.clip(dv_dt, -100.0, 100.0)

        # --- Energy equation ---
        # Total energy: E = p/(Gamma-1) + rho*v^2/2
        epsilon = pressure / (GAMMA - 1)
        total_energy = epsilon + 0.5 * density * Vx ** 2

        # Energy flux: (E + p)*v - v*sigma'
        # where sigma' = (zeta + 4*eta/3)*dv/dx
        energy_flux = (
            (total_energy + pressure) * Vx
            - Vx * (zeta + 4 * eta / 3) * dv_dx
        )

        energy_flux_pad = periodic_pad(energy_flux)
        denergy_flux_dx = (
            (energy_flux_pad[:, 2:] - energy_flux_pad[:, :-2]) / (2 * dx)
        )
        dE_dt = -denergy_flux_dx

        # Derive pressure evolution from energy conservation:
        # dE/dt = dp/dt/(Gamma-1) + d(rho*v^2/2)/dt
        # => dp/dt = (Gamma-1) * (dE/dt - kinetic_energy_change)
        kinetic_energy_change = (
            Vx * density * dv_dt + 0.5 * Vx ** 2 * drho_dt
        )
        dp_dt = (GAMMA - 1) * (dE_dt - kinetic_energy_change)
        dp_dt = np.clip(dp_dt, -100.0 * pressure, 100.0 * pressure)

        return drho_dt, dv_dt, dp_dt

    def euler_step(Vx, density, pressure, dt):
        """Forward Euler time step with stability clamping."""
        drho_dt, dv_dt, dp_dt = compute_rhs(Vx, density, pressure)

        # Replace NaN derivatives with zero for robustness
        drho_dt = np.nan_to_num(drho_dt, nan=0.0)
        dv_dt = np.nan_to_num(dv_dt, nan=0.0)
        dp_dt = np.nan_to_num(dp_dt, nan=0.0)

        Vx_new = Vx + dt * dv_dt
        density_new = np.clip(density + dt * drho_dt, 1e-4, 1e5)
        pressure_new = np.clip(pressure + dt * dp_dt, 1e-4, 1e5)
        return Vx_new, density_new, pressure_new

    def compute_timestep(Vx, density, pressure, remaining_time):
        """Compute CFL-based adaptive time step."""
        sound_speed = np.sqrt(
            GAMMA * pressure / np.clip(density, 1e-4, None)
        )
        max_wave_speed = np.max(np.abs(Vx) + sound_speed)
        hyperbolic_dt = HYPERBOLIC_SAFETY * dx / (max_wave_speed + 1e-6)
        dt = min(hyperbolic_dt, remaining_time, MAX_DT)
        dt = max(dt, MIN_DT)
        return dt

    # Main time-stepping loop
    current_Vx = Vx0.copy()
    current_density = density0.copy()
    current_pressure = pressure0.copy()
    current_time = 0.0

    for i in range(1, T + 1):
        target_time = float(t_coordinate[i])

        while current_time < target_time - 1e-12:
            # NaN recovery: revert to last saved state
            has_nan = (
                np.isnan(current_Vx).any()
                or np.isnan(current_density).any()
                or np.isnan(current_pressure).any()
            )
            if has_nan:
                if i > 1:
                    current_Vx = Vx_pred[:, i - 1].copy()
                    current_density = density_pred[:, i - 1].copy()
                    current_pressure = pressure_pred[:, i - 1].copy()
                else:
                    current_Vx = Vx0.copy()
                    current_density = density0.copy()
                    current_pressure = pressure0.copy()

            remaining_time = target_time - current_time
            dt = compute_timestep(
                current_Vx, current_density, current_pressure,
                remaining_time,
            )

            current_Vx, current_density, current_pressure = euler_step(
                current_Vx, current_density, current_pressure, dt
            )
            current_time += dt

        Vx_pred[:, i] = current_Vx
        density_pred[:, i] = current_density
        pressure_pred[:, i] = current_pressure

    return Vx_pred, density_pred, pressure_pred
