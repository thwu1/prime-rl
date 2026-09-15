//! PC-SAFT equation of state — complete implementation.
//!
//! Reference: Gross & Sadowski, Ind. Eng. Chem. Res. 2001, 40, 1244-1260.


use std::f64::consts::PI;

pub const FRAC_PI_6: f64 = PI / 6.0;
pub const KB: f64 = 1.380649e-23;
pub const NA: f64 = 6.02214076e23;

pub const A0: [f64; 7] = [
    0.91056314451539, 0.63612814494991, 2.68613478913903, -26.5473624914884,
    97.7592087835073, -159.591540865600, 91.2977740839123,
];
pub const A1: [f64; 7] = [
    -0.30840169182720, 0.18605311591713, -2.50300472586548, 21.4197936296668,
    -65.2558853303492, 83.3186804808856, -33.7469229297323,
];
pub const A2: [f64; 7] = [
    -0.09061483509767, 0.45278428063920, 0.59627007280101, -1.72418291311787,
    -4.13021125311661, 13.7766318697211, -8.67284703679646,
];
pub const B0: [f64; 7] = [
    0.72409469413165, 2.23827918609380, -4.00258494846342, -21.00357681484648,
    26.8556413626615, 206.5513384066188, -355.60235612207947,
];
pub const B1: [f64; 7] = [
    -0.57554980753450, 0.69950955214436, 3.89256733895307, -17.21547164777212,
    192.6722644652495, -161.8264616487648, -165.2076934555607,
];
pub const B2: [f64; 7] = [
    0.09768831158356, -0.25575749816100, -9.15585615297321, 20.64207597439724,
    -38.80443005206285, 93.6267740770146, -29.66690558514725,
];

#[derive(Clone, Debug)]
pub struct PcSaftParams {
    pub m: f64,
    pub sigma: f64,
    pub epsilon_k: f64,
}

impl PcSaftParams {
    pub fn propane() -> Self {
        PcSaftParams { m: 2.0018290, sigma: 3.618353, epsilon_k: 208.1101 }
    }
    pub fn butane() -> Self {
        PcSaftParams { m: 2.331586, sigma: 3.7086010, epsilon_k: 222.8774 }
    }
    pub fn methane() -> Self {
        PcSaftParams { m: 1.0, sigma: 3.7039, epsilon_k: 150.034 }
    }
    pub fn max_density(&self) -> f64 {
        0.5 / (self.m * self.sigma.powi(3) * FRAC_PI_6)
    }
}

// ============================================================================
// Helmholtz energy contributions
// ============================================================================

pub fn hs_diameter(temperature: f64, params: &PcSaftParams) -> f64 {
    params.sigma * (1.0 - 0.12 * (-3.0 * params.epsilon_k / temperature).exp())
}

pub fn packing_fraction(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    let d = hs_diameter(temperature, params);
    FRAC_PI_6 * density * params.m * d.powi(3)
}

pub fn a_hard_sphere(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    let eta = packing_fraction(temperature, density, params);
    let one_m_eta = 1.0 - eta;
    params.m * density * (4.0 * eta - 3.0 * eta * eta) / (one_m_eta * one_m_eta)
}

pub fn a_hard_chain(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    if (params.m - 1.0).abs() < 1e-15 {
        return 0.0;
    }
    let eta = packing_fraction(temperature, density, params);
    let one_m_eta = 1.0 - eta;
    let g_hs = (1.0 - 0.5 * eta) / (one_m_eta * one_m_eta * one_m_eta);
    -density * (params.m - 1.0) * g_hs.ln()
}

pub fn a_dispersion(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    let eta = packing_fraction(temperature, density, params);
    let m = params.m;
    let e = params.epsilon_k / temperature;
    let sigma3 = params.sigma.powi(3);

    let m1_m = (m - 1.0) / m;
    let m2_m = (m - 2.0) / m;

    let mut i1 = 0.0_f64;
    let mut i2 = 0.0_f64;
    let mut eta_i = 1.0_f64;
    for i in 0..7 {
        i1 += (A0[i] + m1_m * (A1[i] + m2_m * A2[i])) * eta_i;
        i2 += (B0[i] + m1_m * (B1[i] + m2_m * B2[i])) * eta_i;
        eta_i *= eta;
    }

    // Compressibility expression C1
    let one_m_eta = 1.0 - eta;
    let eta2 = eta * eta;
    let eta3 = eta2 * eta;
    let eta4 = eta2 * eta2;

    let c1 = (1.0
        + m * (8.0 * eta - 2.0 * eta2) / (one_m_eta.powi(4))
        + (1.0 - m) * (20.0 * eta - 27.0 * eta2 + 12.0 * eta3 - 2.0 * eta4)
            / ((one_m_eta * (2.0 - eta)).powi(2)))
    .recip();

    -PI * density * density * m * m * e * sigma3 * (2.0 * i1 + c1 * m * e * i2)
}

pub fn a_residual(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    a_hard_sphere(temperature, density, params)
        + a_hard_chain(temperature, density, params)
        + a_dispersion(temperature, density, params)
}

// ============================================================================
// Thermodynamic properties via numerical differentiation
// ============================================================================

pub fn pressure_reduced(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    let phi = a_residual(temperature, density, params);
    let h = density * 1e-8;
    let phi_plus = a_residual(temperature, density + h, params);
    let phi_minus = a_residual(temperature, density - h, params);
    let dphi_drho = (phi_plus - phi_minus) / (2.0 * h);
    // P/(kT) = rho (ideal) + rho * dPhi/drho - Phi (residual)
    density + density * dphi_drho - phi
}

pub fn chemical_potential_res(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    let h = density * 1e-8;
    let phi_plus = a_residual(temperature, density + h, params);
    let phi_minus = a_residual(temperature, density - h, params);
    (phi_plus - phi_minus) / (2.0 * h)
}

// ============================================================================
// Density solver — Newton's method with damping
// ============================================================================

pub fn find_density(
    temperature: f64,
    pressure_red: f64,
    params: &PcSaftParams,
    is_liquid: bool,
) -> Option<f64> {
    let rho_max = params.max_density();

    // Initial guess
    let mut rho = if is_liquid {
        0.7 * rho_max
    } else {
        // Ideal gas: P/(kT) = rho
        pressure_red.max(1e-20)
    };

    for _ in 0..300 {
        if rho <= 0.0 {
            rho = 1e-18;
        }
        if rho >= 0.99 * rho_max {
            rho = 0.95 * rho_max;
        }

        let p = pressure_reduced(temperature, rho, params);
        let h = rho.max(1e-18) * 1e-6;
        let dp = (pressure_reduced(temperature, rho + h, params)
            - pressure_reduced(temperature, rho - h, params))
            / (2.0 * h);

        if dp.abs() < 1e-30 {
            break;
        }

        let mut delta = (p - pressure_red) / dp;

        // Damping: limit step to 30% of current density
        let max_step = 0.3 * rho;
        if delta > max_step {
            delta = max_step;
        }
        if delta < -max_step {
            delta = -max_step;
        }

        rho -= delta;

        if rho <= 0.0 {
            rho = 1e-18;
        }

        if delta.abs() / rho.max(1e-18) < 1e-12 {
            return Some(rho);
        }
    }

    Some(rho)
}

// ============================================================================
// Vapor-liquid equilibrium solver — bisection on chemical potential
// ============================================================================

pub fn vapor_pressure(temperature: f64, params: &PcSaftParams) -> Option<(f64, f64, f64)> {
    let rho_max = params.max_density();

    // Scan the pressure-density isotherm to find the van der Waals loop
    let n_scan: usize = 2000;
    let mut pressures = Vec::with_capacity(n_scan);
    let mut densities = Vec::with_capacity(n_scan);

    for i in 1..=n_scan {
        let rho = rho_max * 0.9 * (i as f64) / (n_scan as f64);
        let p = pressure_reduced(temperature, rho, params);
        pressures.push(p);
        densities.push(rho);
    }

    // Find the local maximum (liquid spinodal) and minimum (vapor spinodal)
    let mut p_max_val = f64::NEG_INFINITY;
    let mut p_min_val = f64::INFINITY;
    let mut found_max = false;
    let mut found_min = false;

    for i in 1..pressures.len() - 1 {
        if !found_max && pressures[i] > pressures[i - 1] && pressures[i] > pressures[i + 1] {
            p_max_val = pressures[i];
            found_max = true;
        }
        if found_max
            && !found_min
            && pressures[i] < pressures[i - 1]
            && pressures[i] < pressures[i + 1]
        {
            p_min_val = pressures[i];
            found_min = true;
            break;
        }
    }

    if !found_max || !found_min {
        return None; // No van der Waals loop — supercritical
    }

    // Bisect on pressure to find where chemical potentials are equal
    let mut p_lo = if p_min_val > 0.0 { p_min_val } else { 1e-20 };
    let mut p_hi = p_max_val;

    for _ in 0..300 {
        let p_mid = 0.5 * (p_lo + p_hi);

        let rho_v = match find_density(temperature, p_mid, params, false) {
            Some(r) if r > 0.0 => r,
            _ => return None,
        };
        let rho_l = match find_density(temperature, p_mid, params, true) {
            Some(r) if r > 0.0 => r,
            _ => return None,
        };

        // Ensure we have distinct roots
        if (rho_l - rho_v).abs() / rho_l < 1e-6 {
            return None;
        }

        // Total chemical potential: mu/(kT) = ln(rho) + mu_res/(kT)
        let mu_v = chemical_potential_res(temperature, rho_v, params) + rho_v.ln();
        let mu_l = chemical_potential_res(temperature, rho_l, params) + rho_l.ln();
        let dmu = mu_v - mu_l;

        if dmu.abs() < 1e-14 {
            return Some((p_mid, rho_v, rho_l));
        }

        // When dmu > 0: pressure is above Psat (liquid favored) -> decrease P
        // When dmu < 0: pressure is below Psat (vapor favored)  -> increase P
        if dmu > 0.0 {
            p_hi = p_mid;
        } else {
            p_lo = p_mid;
        }
    }

    let p_mid = 0.5 * (p_lo + p_hi);
    let rho_v = find_density(temperature, p_mid, params, false)?;
    let rho_l = find_density(temperature, p_mid, params, true)?;
    Some((p_mid, rho_v, rho_l))
}

// ============================================================================
// Critical point finder — scan-based approach
//
// 1. Binary search on T to find where the van der Waals loop vanishes (= Tc)
// 2. At T slightly below Tc, find spinodal densities (P local max/min)
// 3. Refine spinodals with Newton on dP/drho=0, then rhoc = midpoint
// ============================================================================

/// Check if the P(rho) isotherm has a van der Waals loop at temperature t.
/// Returns Some((rho_at_Pmax, rho_at_Pmin)) if loop found, None otherwise.
fn find_pressure_loop(t: f64, params: &PcSaftParams) -> Option<(f64, f64)> {
    let rho_max = params.max_density();
    let n: usize = 5000;
    let mut pp: f64 = 0.0;
    let mut ppp: f64 = 0.0;
    let mut rho_pmax: f64 = 0.0;
    let mut found_max = false;

    for i in 1..=n {
        let rho = rho_max * 0.9 * (i as f64) / (n as f64);
        let p = pressure_reduced(t, rho, params);

        if i >= 3 {
            if pp > ppp && pp > p && !found_max {
                rho_pmax = rho_max * 0.9 * ((i - 1) as f64) / (n as f64);
                found_max = true;
            }
            if found_max && pp < ppp && pp < p {
                let rho_pmin = rho_max * 0.9 * ((i - 1) as f64) / (n as f64);
                return Some((rho_pmax, rho_pmin));
            }
        }
        ppp = pp;
        pp = p;
    }
    None
}

/// Refine a spinodal density (where dP/drho = 0) using Newton's method.
fn refine_spinodal(t: f64, rho_init: f64, params: &PcSaftParams) -> f64 {
    let mut rho = rho_init;
    for _ in 0..100 {
        let h = rho * 1e-5;
        // dP/drho via central difference
        let dp = (pressure_reduced(t, rho + h, params) - pressure_reduced(t, rho - h, params))
            / (2.0 * h);
        // d2P/drho2
        let d2p = (pressure_reduced(t, rho + h, params)
            - 2.0 * pressure_reduced(t, rho, params)
            + pressure_reduced(t, rho - h, params))
            / (h * h);

        if d2p.abs() < 1e-30 {
            break;
        }
        let delta = dp / d2p;
        rho -= delta;
        if rho <= 0.0 {
            rho = 1e-15;
        }
        if delta.abs() / rho < 1e-10 {
            break;
        }
    }
    rho
}

pub fn critical_point(params: &PcSaftParams) -> (f64, f64) {
    // Step 1: Binary search for Tc
    let mut t_lo = params.epsilon_k;
    let mut t_hi = 3.0 * params.epsilon_k;

    for _ in 0..80 {
        let t_mid = 0.5 * (t_lo + t_hi);
        if find_pressure_loop(t_mid, params).is_some() {
            t_lo = t_mid;
        } else {
            t_hi = t_mid;
        }
    }
    let tc = 0.5 * (t_lo + t_hi);

    // Step 2: Find critical density from refined spinodal midpoint
    let mut rhoc = 0.3 * params.max_density();
    for &dt in &[0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0] {
        if let Some((rho1, rho2)) = find_pressure_loop(tc - dt, params) {
            let rho1r = refine_spinodal(tc - dt, rho1, params);
            let rho2r = refine_spinodal(tc - dt, rho2, params);
            rhoc = 0.5 * (rho1r + rho2r);
            break;
        }
    }

    (tc, rhoc)
}
