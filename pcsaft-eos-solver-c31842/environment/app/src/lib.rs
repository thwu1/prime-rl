//! PC-SAFT (Perturbed-Chain Statistical Associating Fluid Theory) equation of state
//! for pure non-associating components.
//!
//! # Unit conventions
//!
//! All internal quantities use "molecular" reduced units:
//! - Temperature: Kelvin (K)
//! - Length / segment diameter: Angstrom (A)
//! - Number density rho: particles per A^3 (1/A^3)
//! - Reduced Helmholtz energy density Phi = A_res / (k_B * T * V)  in 1/A^3
//! - Reduced pressure P_red = P / (k_B * T) in 1/A^3
//! - Reduced chemical potential mu_res / (k_B * T) is dimensionless
//!
//! # References
//!
//! Gross, J.; Sadowski, G. Perturbed-Chain SAFT: An Equation of State Based on
//! a Perturbation Theory for Chain Molecules. Ind. Eng. Chem. Res. 2001, 40, 1244-1260.


use std::f64::consts::PI;

/// pi / 6
pub const FRAC_PI_6: f64 = PI / 6.0;

/// Boltzmann constant in J/K
pub const KB: f64 = 1.380649e-23;

/// Avogadro's number in 1/mol
pub const NA: f64 = 6.02214076e23;

// ============================================================================
// Universal model constants for the PC-SAFT dispersion term
// (Table 1 of Gross & Sadowski 2001)
//
// The coefficients a_i(m) and b_i(m) for the power series I_1 and I_2 are:
//   a_i(m) = A0[i] + ((m-1)/m)*A1[i] + ((m-1)/m)*((m-2)/m)*A2[i]
//   b_i(m) = B0[i] + ((m-1)/m)*B1[i] + ((m-1)/m)*((m-2)/m)*B2[i]
// ============================================================================

pub const A0: [f64; 7] = [
    0.91056314451539,
    0.63612814494991,
    2.68613478913903,
    -26.5473624914884,
    97.7592087835073,
    -159.591540865600,
    91.2977740839123,
];

pub const A1: [f64; 7] = [
    -0.30840169182720,
    0.18605311591713,
    -2.50300472586548,
    21.4197936296668,
    -65.2558853303492,
    83.3186804808856,
    -33.7469229297323,
];

pub const A2: [f64; 7] = [
    -0.09061483509767,
    0.45278428063920,
    0.59627007280101,
    -1.72418291311787,
    -4.13021125311661,
    13.7766318697211,
    -8.67284703679646,
];

pub const B0: [f64; 7] = [
    0.72409469413165,
    2.23827918609380,
    -4.00258494846342,
    -21.00357681484648,
    26.8556413626615,
    206.5513384066188,
    -355.60235612207947,
];

pub const B1: [f64; 7] = [
    -0.57554980753450,
    0.69950955214436,
    3.89256733895307,
    -17.21547164777212,
    192.6722644652495,
    -161.8264616487648,
    -165.2076934555607,
];

pub const B2: [f64; 7] = [
    0.09768831158356,
    -0.25575749816100,
    -9.15585615297321,
    20.64207597439724,
    -38.80443005206285,
    93.6267740770146,
    -29.66690558514725,
];

// ============================================================================
// Parameter definitions
// ============================================================================

/// PC-SAFT pure component parameters for non-associating molecules.
#[derive(Clone, Debug)]
pub struct PcSaftParams {
    /// Segment number (chain length parameter)
    pub m: f64,
    /// Segment diameter in Angstrom
    pub sigma: f64,
    /// Energetic parameter epsilon/k_B in Kelvin
    pub epsilon_k: f64,
}

impl PcSaftParams {
    /// Propane parameters (Gross & Sadowski 2001)
    pub fn propane() -> Self {
        PcSaftParams {
            m: 2.0018290,
            sigma: 3.618353,
            epsilon_k: 208.1101,
        }
    }

    /// Butane parameters (Gross & Sadowski 2001)
    pub fn butane() -> Self {
        PcSaftParams {
            m: 2.331586,
            sigma: 3.7086010,
            epsilon_k: 222.8774,
        }
    }

    /// Methane parameters (Gross & Sadowski 2001)
    pub fn methane() -> Self {
        PcSaftParams {
            m: 1.0,
            sigma: 3.7039,
            epsilon_k: 150.034,
        }
    }

    /// Maximum number density (close-packing limit at eta_max = 0.5).
    /// rho_max = eta_max / (m * sigma^3 * pi/6)
    pub fn max_density(&self) -> f64 {
        0.5 / (self.m * self.sigma.powi(3) * FRAC_PI_6)
    }
}

// ============================================================================
// Helmholtz energy contributions
//
// Each function returns the reduced Helmholtz energy DENSITY:
//   Phi = A_contribution / (k_B * T * V)
// in units of 1/A^3.
//
// To obtain the dimensionless Helmholtz energy A/(k_B*T), multiply by V.
// ============================================================================

/// Temperature-dependent hard-sphere diameter.
///
/// d(T) = sigma * [1 - 0.12 * exp(-3 * epsilon_k / T)]
pub fn hs_diameter(temperature: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement temperature-dependent hard-sphere diameter")
}

/// Packing fraction (reduced density).
///
/// eta = (pi/6) * rho * m * d(T)^3
pub fn packing_fraction(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement packing fraction calculation")
}

/// Hard-sphere contribution to the reduced Helmholtz energy density.
///
/// For a pure fluid of m-segment chains (Carnahan-Starling per-segment):
///   Phi_hs = m * rho * (4*eta - 3*eta^2) / (1 - eta)^2
pub fn a_hard_sphere(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement hard-sphere Helmholtz energy contribution")
}

/// Hard-chain contribution to the reduced Helmholtz energy density.
///
/// Phi_hc = -rho * (m - 1) * ln(g_hs)
///
/// where g_hs is the contact value of the hard-sphere radial distribution function:
///   g_hs = (1 - eta/2) / (1 - eta)^3
pub fn a_hard_chain(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement hard-chain Helmholtz energy contribution")
}

/// Dispersion (attraction) contribution to the reduced Helmholtz energy density.
///
/// Phi_disp = -PI * rho^2 * m^2 * (eps_k/T) * sigma^3 * [2*I1 + C1*m*(eps_k/T)*I2]
///
/// Power series:
///   I1 = sum_{i=0}^{6} a_i(m) * eta^i
///   I2 = sum_{i=0}^{6} b_i(m) * eta^i
///
/// where:
///   a_i(m) = A0[i] + ((m-1)/m)*A1[i] + ((m-1)/m)*((m-2)/m)*A2[i]
///   b_i(m) = B0[i] + ((m-1)/m)*B1[i] + ((m-1)/m)*((m-2)/m)*B2[i]
///
/// Compressibility expression:
///   C1 = [1 + m*(8*eta - 2*eta^2)/(1-eta)^4
///         + (1-m)*(20*eta - 27*eta^2 + 12*eta^3 - 2*eta^4)
///           / ((1-eta)*(2-eta))^2 ]^(-1)
pub fn a_dispersion(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement dispersion Helmholtz energy contribution")
}

/// Total residual reduced Helmholtz energy density (sum of all contributions).
pub fn a_residual(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    a_hard_sphere(temperature, density, params)
        + a_hard_chain(temperature, density, params)
        + a_dispersion(temperature, density, params)
}

// ============================================================================
// Thermodynamic properties derived from the Helmholtz energy density
// ============================================================================

/// Reduced pressure P/(k_B*T) in units of 1/A^3.
///
/// From the Helmholtz energy density Phi(T, rho):
///   P/(kT) = rho + rho * dPhi/drho - Phi
///
/// where dPhi/drho is the partial derivative at constant T.
pub fn pressure_reduced(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement reduced pressure calculation")
}

/// Residual chemical potential in units of kT (dimensionless).
///
/// For a pure component:
///   mu_res/(kT) = dPhi/drho
///
/// where Phi is the total residual Helmholtz energy density.
pub fn chemical_potential_res(temperature: f64, density: f64, params: &PcSaftParams) -> f64 {
    todo!("Implement residual chemical potential")
}

// ============================================================================
// Solvers
// ============================================================================

/// Find the number density rho (1/A^3) at given temperature and reduced pressure
/// for the specified phase.
///
/// Two roots generally exist below the critical temperature: a low-density (vapor)
/// root and a high-density (liquid) root.
pub fn find_density(
    temperature: f64,
    pressure_red: f64,
    params: &PcSaftParams,
    is_liquid: bool,
) -> Option<f64> {
    todo!("Implement density solver")
}

/// Pure-component vapor-liquid equilibrium at given temperature.
///
/// Finds the saturation condition where both phases have equal pressure
/// and equal chemical potential:
///   P(T, rho_v) = P(T, rho_l)
///   mu(T, rho_v) = mu(T, rho_l)
///
/// The total chemical potential (including ideal contribution) is:
///   mu/(kT) = ln(rho) + mu_res/(kT)
///
/// Returns (P_sat_reduced, rho_vapor, rho_liquid), or None if T >= Tc.
pub fn vapor_pressure(temperature: f64, params: &PcSaftParams) -> Option<(f64, f64, f64)> {
    todo!("Implement vapor-liquid equilibrium solver")
}

/// Find the critical point of a pure component.
///
/// At the critical point, the first and second derivatives of pressure
/// with respect to density vanish simultaneously:
///   (dP/drho)_T = 0
///   (d^2 P / drho^2)_T = 0
///
/// Returns (T_c in Kelvin, rho_c in 1/A^3).
pub fn critical_point(params: &PcSaftParams) -> (f64, f64) {
    todo!("Implement critical point finder")
}
