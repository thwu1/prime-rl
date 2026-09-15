"""Generate reference data for the CNS1D solver task.

This script implements a correct 1D compressible Navier-Stokes solver,
generates synthetic initial conditions, runs the solver for two parameter
regimes, and saves the reference solutions to /tmp/reference.h5 in HDF5 format.

This file is used during Docker build (stage 1) and is NOT included
in the final image.
"""
import numpy as np
import h5py


def correct_solver(Vx0, density0, pressure0, t_coordinate, eta, zeta):
    """Correct CNS1D solver using forward Euler with central FDM."""
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
        return np.concatenate([x[:, -2:-1], x, x[:, 1:2]], axis=1)

    def compute_rhs(Vx, density, pressure):
        Vx_pad = periodic_pad(Vx)
        density_pad = periodic_pad(density)
        pressure_pad = periodic_pad(pressure)

        dv_dx = (Vx_pad[:, 2:] - Vx_pad[:, :-2]) / (2 * dx)
        d2v_dx2 = (Vx_pad[:, 2:] - 2 * Vx + Vx_pad[:, :-2]) / (dx ** 2)

        rho_v = density * Vx
        rho_v_pad = periodic_pad(rho_v)
        drho_v_dx = (rho_v_pad[:, 2:] - rho_v_pad[:, :-2]) / (2 * dx)
        drho_dt = -drho_v_dx

        pressure_grad = (pressure_pad[:, 2:] - pressure_pad[:, :-2]) / (2 * dx)
        safe_density = np.clip(density, 1e-4, None)

        dv_dt = (
            -Vx * dv_dx
            - pressure_grad / safe_density
            + (eta + zeta + eta / 3) * d2v_dx2
        )

        div_v = dv_dx
        art_visc = (
            ARTIFICIAL_VISCOSITY_COEFF * density * dx ** 2
            * np.abs(div_v) * div_v
        )
        dv_dt = dv_dt + art_visc
        dv_dt = np.clip(dv_dt, -100.0, 100.0)

        epsilon = pressure / (GAMMA - 1)
        total_energy = epsilon + 0.5 * density * Vx ** 2
        energy_flux = (
            (total_energy + pressure) * Vx
            - Vx * (zeta + 4 * eta / 3) * dv_dx
        )

        energy_flux_pad = periodic_pad(energy_flux)
        denergy_flux_dx = (
            (energy_flux_pad[:, 2:] - energy_flux_pad[:, :-2]) / (2 * dx)
        )
        dE_dt = -denergy_flux_dx

        kinetic_energy_change = Vx * density * dv_dt + 0.5 * Vx ** 2 * drho_dt
        dp_dt = (GAMMA - 1) * (dE_dt - kinetic_energy_change)
        dp_dt = np.clip(dp_dt, -100.0 * pressure, 100.0 * pressure)

        return drho_dt, dv_dt, dp_dt

    def euler_step(Vx, density, pressure, dt):
        drho_dt, dv_dt, dp_dt = compute_rhs(Vx, density, pressure)
        drho_dt = np.nan_to_num(drho_dt, nan=0.0)
        dv_dt = np.nan_to_num(dv_dt, nan=0.0)
        dp_dt = np.nan_to_num(dp_dt, nan=0.0)

        Vx_new = Vx + dt * dv_dt
        density_new = np.clip(density + dt * drho_dt, 1e-4, 1e5)
        pressure_new = np.clip(pressure + dt * dp_dt, 1e-4, 1e5)
        return Vx_new, density_new, pressure_new

    def compute_timestep(Vx, density, pressure, remaining_time):
        sound_speed = np.sqrt(GAMMA * pressure / np.clip(density, 1e-4, None))
        max_wave_speed = np.max(np.abs(Vx) + sound_speed)
        hyperbolic_dt = HYPERBOLIC_SAFETY * dx / (max_wave_speed + 1e-6)
        dt = min(hyperbolic_dt, remaining_time, MAX_DT)
        dt = max(dt, MIN_DT)
        return dt

    current_Vx = Vx0.copy()
    current_density = density0.copy()
    current_pressure = pressure0.copy()
    current_time = 0.0

    for i in range(1, T + 1):
        target_time = float(t_coordinate[i])

        while current_time < target_time - 1e-12:
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
                current_Vx, current_density, current_pressure, remaining_time
            )
            current_Vx, current_density, current_pressure = euler_step(
                current_Vx, current_density, current_pressure, dt
            )
            current_time += dt

        Vx_pred[:, i] = current_Vx
        density_pred[:, i] = current_density
        pressure_pred[:, i] = current_pressure

    return Vx_pred, density_pred, pressure_pred


def generate_initial_conditions(N, batch_size, seed=42):
    """Generate smooth periodic initial conditions for the CNS1D equations."""
    rng = np.random.default_rng(seed)
    x = np.linspace(-1, 1, N)

    Vx0 = np.zeros((batch_size, N), dtype=np.float64)
    density0 = np.ones((batch_size, N), dtype=np.float64)
    pressure0 = np.ones((batch_size, N), dtype=np.float64)

    for b in range(batch_size):
        n_vel_modes = rng.integers(2, 5)
        modes = rng.choice(range(1, 6), size=n_vel_modes, replace=False)
        for k in modes:
            amp = rng.uniform(-0.3, 0.3)
            Vx0[b] += amp * np.sin(k * np.pi * x)

        n_den_modes = rng.integers(1, 3)
        modes = rng.choice(range(1, 4), size=n_den_modes, replace=False)
        for k in modes:
            amp = rng.uniform(0.05, 0.15)
            density0[b] += amp * np.cos(k * np.pi * x)

        n_pres_modes = rng.integers(1, 3)
        modes = rng.choice(range(1, 4), size=n_pres_modes, replace=False)
        for k in modes:
            amp = rng.uniform(0.05, 0.15)
            pressure0[b] += amp * np.cos(k * np.pi * x)

    return Vx0, density0, pressure0


if __name__ == "__main__":
    N = 128
    batch_size = 4
    t_coordinate = np.linspace(0, 0.2, 11)

    regimes = [
        {"eta": 0.1, "zeta": 0.1, "name": "high_viscosity"},
        {"eta": 0.01, "zeta": 0.01, "name": "low_viscosity"},
    ]

    with h5py.File("/tmp/reference.h5", "w") as f:
        f.attrs["description"] = "CNS1D reference solutions for solver validation"
        f.attrs["gamma"] = 5.0 / 3.0
        f.attrs["domain"] = np.array([-1.0, 1.0])
        f.attrs["grid_type"] = "vertex-centered"

        for regime in regimes:
            eta = regime["eta"]
            zeta = regime["zeta"]
            name = regime["name"]

            Vx0, density0, pressure0 = generate_initial_conditions(
                N, batch_size, seed=42
            )

            print(
                f"Generating {name}: N={N}, batch={batch_size}, "
                f"eta={eta}, zeta={zeta}"
            )

            Vx_ref, density_ref, pressure_ref = correct_solver(
                Vx0, density0, pressure0, t_coordinate, eta, zeta
            )

            print(
                f"  Final Vx range: "
                f"[{Vx_ref[:, -1].min():.4f}, {Vx_ref[:, -1].max():.4f}]"
            )
            print(
                f"  Final density range: "
                f"[{density_ref[:, -1].min():.4f}, "
                f"{density_ref[:, -1].max():.4f}]"
            )
            print(
                f"  Final pressure range: "
                f"[{pressure_ref[:, -1].min():.4f}, "
                f"{pressure_ref[:, -1].max():.4f}]"
            )

            grp = f.create_group(name)
            grp.attrs["eta"] = eta
            grp.attrs["zeta"] = zeta
            grp.attrs["N"] = N
            grp.attrs["batch_size"] = batch_size

            init_grp = grp.create_group("initial_conditions")
            init_grp.create_dataset("velocity", data=Vx0)
            init_grp.create_dataset("density", data=density0)
            init_grp.create_dataset("pressure", data=pressure0)

            ref_grp = grp.create_group("reference_solution")
            ref_grp.create_dataset("velocity", data=Vx_ref)
            ref_grp.create_dataset("density", data=density_ref)
            ref_grp.create_dataset("pressure", data=pressure_ref)

            grp.create_dataset("t_coordinate", data=t_coordinate)

    print("Reference data saved to /tmp/reference.h5")
