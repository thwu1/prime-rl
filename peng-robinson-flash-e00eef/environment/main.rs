use std::fs;
use std::f64::consts::{PI, SQRT_2};
use serde::{Deserialize, Serialize};

/// Universal gas constant in J/(mol·K)
const R: f64 = 8.31446261815324;

/// Component parameters for the Peng-Robinson equation of state.
#[derive(Debug, Clone, Deserialize)]
pub struct Component {
    /// Component name
    pub name: String,
    /// Critical temperature (K)
    pub tc: f64,
    /// Critical pressure (Pa)
    pub pc: f64,
    /// Acentric factor (dimensionless)
    pub omega: f64,
    /// Molar weight (g/mol)
    pub molarweight: f64,
}

/// Computed results to be written as JSON.
#[derive(Debug, Serialize)]
pub struct Results {
    pub propane_psat_300K_Pa: f64,
    pub butane_psat_350K_Pa: f64,
    pub propane_butane_bubble_300K_Pa: f64,
    pub propane_butane_dew_300K_Pa: f64,
    pub flash_vapor_fraction: f64,
    pub flash_liquid_composition: Vec<f64>,
    pub flash_vapor_composition: Vec<f64>,
    pub propane_hvap_300K_J_per_mol: f64,
    pub propane_z_liq_300K: f64,
    pub propane_cv_res_liq_300K_J_per_molK: f64,
}

// =========================================================================
// PR EoS parameter functions
// =========================================================================

fn pr_ac(comp: &Component) -> f64 {
    0.45724 * R * R * comp.tc * comp.tc / comp.pc
}

fn pr_b(comp: &Component) -> f64 {
    0.07780 * R * comp.tc / comp.pc
}

fn pr_kappa(comp: &Component) -> f64 {
    0.37464 + 1.54226 * comp.omega - 0.26992 * comp.omega * comp.omega
}

fn pr_alpha(t: f64, comp: &Component) -> f64 {
    let tr = t / comp.tc;
    let v = 1.0 + pr_kappa(comp) * (1.0 - tr.sqrt());
    v * v
}

fn pr_a(t: f64, comp: &Component) -> f64 {
    pr_ac(comp) * pr_alpha(t, comp)
}

// =========================================================================
// Cubic equation solver for PR EoS
// Solves: Z^3 - (1-B)Z^2 + (A - 3B^2 - 2B)Z - (AB - B^2 - B^3) = 0
// Returns real roots Z > B, sorted ascending.
// =========================================================================

fn solve_cubic_pr(a_coeff: f64, b_coeff: f64) -> Vec<f64> {
    let c2 = -(1.0 - b_coeff);
    let c1 = a_coeff - 3.0 * b_coeff * b_coeff - 2.0 * b_coeff;
    let c0 = -(a_coeff * b_coeff - b_coeff * b_coeff - b_coeff.powi(3));

    // Depressed cubic t^3 + pt + q = 0 via Z = t - c2/3
    let p = c1 - c2 * c2 / 3.0;
    let q = c0 + c1 * c2 / 3.0 + 2.0 * c2.powi(3) / 27.0;

    let disc = -4.0 * p.powi(3) - 27.0 * q * q;
    let shift = -c2 / 3.0;

    let mut roots = Vec::with_capacity(3);

    if disc > 1e-14 {
        // Three distinct real roots — trigonometric solution
        let r_val = (-p / 3.0).sqrt();
        let cos_arg = (-q / (2.0 * r_val.powi(3))).clamp(-1.0, 1.0);
        let theta = cos_arg.acos();
        for k in 0..3 {
            let root =
                2.0 * r_val * ((theta + 2.0 * PI * k as f64) / 3.0).cos() + shift;
            if root > b_coeff + 1e-15 {
                roots.push(root);
            }
        }
        roots.sort_by(|a, b| a.partial_cmp(b).unwrap());
    } else {
        // One real root (or repeated)
        let det = q * q / 4.0 + p.powi(3) / 27.0;
        if det >= 0.0 {
            let sd = det.sqrt();
            let u = (-q / 2.0 + sd).cbrt();
            let v = (-q / 2.0 - sd).cbrt();
            let root = u + v + shift;
            if root > b_coeff + 1e-15 {
                roots.push(root);
            }
        }
    }
    roots
}

// =========================================================================
// Fugacity coefficients
// =========================================================================

/// Pure-component fugacity coefficient from PR EoS.
fn fugacity_coeff_pure(t: f64, p: f64, comp: &Component, vapor: bool) -> f64 {
    let a = pr_a(t, comp);
    let b = pr_b(comp);
    let big_a = a * p / (R * R * t * t);
    let big_b = b * p / (R * t);

    let roots = solve_cubic_pr(big_a, big_b);
    if roots.is_empty() {
        return 1.0;
    }
    let z = if vapor {
        *roots.last().unwrap()
    } else {
        *roots.first().unwrap()
    };

    let ln_phi = z - 1.0
        - (z - big_b).ln()
        - big_a / (2.0 * SQRT_2 * big_b)
            * ((z + (1.0 + SQRT_2) * big_b) / (z + (1.0 - SQRT_2) * big_b)).ln();
    ln_phi.exp()
}

/// Mixture fugacity coefficient for component `idx` from PR EoS with VDW mixing rules.
fn fugacity_coeff_mix(
    _t: f64,
    _p: f64,
    _comps: &[Component],
    _x: &[f64],
    _kij: &[Vec<f64>],
    _idx: usize,
    _vapor: bool,
) -> f64 {
    todo!("Implement mixture fugacity coefficient")
}

// =========================================================================
// VLE calculations
// =========================================================================

/// Saturation (vapor) pressure of a pure component at temperature t (K).
fn vapor_pressure(_t: f64, _comp: &Component) -> f64 {
    todo!("Implement pure-component saturation pressure")
}

/// Bubble-point pressure for a mixture at temperature t (K).
fn bubble_point_pressure(
    _t: f64,
    _comps: &[Component],
    _x: &[f64],
    _kij: &[Vec<f64>],
) -> f64 {
    todo!("Implement mixture bubble-point pressure")
}

/// Dew-point pressure for a mixture at temperature t (K).
fn dew_point_pressure(
    _t: f64,
    _comps: &[Component],
    _y: &[f64],
    _kij: &[Vec<f64>],
) -> f64 {
    todo!("Implement mixture dew-point pressure")
}

/// Isothermal (T-P) flash calculation.
/// Returns (vapor_fraction, liquid_mole_fractions, vapor_mole_fractions).
fn flash_tp(
    _t: f64,
    _p: f64,
    _comps: &[Component],
    _z: &[f64],
    _kij: &[Vec<f64>],
) -> (f64, Vec<f64>, Vec<f64>) {
    todo!("Implement isothermal flash")
}

// =========================================================================
// Thermodynamic departure properties
// =========================================================================

/// PR enthalpy departure (H - H^ig) at given T, P for a pure component.
fn enthalpy_departure(_t: f64, _p: f64, _comp: &Component, _vapor: bool) -> f64 {
    todo!("Implement PR enthalpy departure function")
}

/// Molar enthalpy of vaporization at temperature t (K).
fn enthalpy_of_vaporization(_t: f64, _comp: &Component) -> f64 {
    todo!("Implement enthalpy of vaporization")
}

/// Liquid compressibility factor at saturation conditions.
fn z_liquid_at_saturation(_t: f64, _comp: &Component) -> f64 {
    todo!("Compute liquid-phase Z at saturation")
}

/// Residual isochoric heat capacity Cv^res at given T, P for a pure component.
fn cv_residual(_t: f64, _p: f64, _comp: &Component, _vapor: bool) -> f64 {
    todo!("Implement residual Cv from PR second temperature derivative")
}

fn main() {
    let data = fs::read_to_string("/app/data/components.json")
        .expect("Failed to read components.json");
    let components: Vec<Component> =
        serde_json::from_str(&data).expect("Failed to parse JSON");

    let propane = components.iter().find(|c| c.name == "propane").unwrap().clone();
    let butane = components.iter().find(|c| c.name == "butane").unwrap().clone();
    let pentane = components.iter().find(|c| c.name == "pentane").unwrap().clone();

    let kij_2 = vec![vec![0.0; 2]; 2];
    let kij_3 = vec![vec![0.0; 3]; 3];

    // Pure component vapor pressures
    let propane_psat = vapor_pressure(300.0, &propane);
    let butane_psat = vapor_pressure(350.0, &butane);

    // Binary VLE
    let bubble_p = bubble_point_pressure(
        300.0,
        &[propane.clone(), butane.clone()],
        &[0.4, 0.6],
        &kij_2,
    );
    let dew_p = dew_point_pressure(
        300.0,
        &[propane.clone(), butane.clone()],
        &[0.4, 0.6],
        &kij_2,
    );

    // Ternary flash
    let (flash_beta, flash_x, flash_y) = flash_tp(
        300.0,
        250000.0,
        &[propane.clone(), butane.clone(), pentane.clone()],
        &[0.2, 0.3, 0.5],
        &kij_3,
    );

    // Thermodynamic properties at saturation
    let hvap = enthalpy_of_vaporization(300.0, &propane);
    let z_liq = z_liquid_at_saturation(300.0, &propane);
    let cv_res = cv_residual(300.0, propane_psat, &propane, false);

    let results = Results {
        propane_psat_300K_Pa: propane_psat,
        butane_psat_350K_Pa: butane_psat,
        propane_butane_bubble_300K_Pa: bubble_p,
        propane_butane_dew_300K_Pa: dew_p,
        flash_vapor_fraction: flash_beta,
        flash_liquid_composition: flash_x,
        flash_vapor_composition: flash_y,
        propane_hvap_300K_J_per_mol: hvap,
        propane_z_liq_300K: z_liq,
        propane_cv_res_liq_300K_J_per_molK: cv_res,
    };

    let output = serde_json::to_string_pretty(&results).unwrap();
    fs::write("/app/results.json", &output).unwrap();
    println!("{}", output);
}
