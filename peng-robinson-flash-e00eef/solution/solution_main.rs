//
// Complete Peng-Robinson EoS implementation with VLE, flash, departure
// functions, dew-point, liquid Z, and residual Cv.

use serde::{Deserialize, Serialize};
use std::f64::consts::{PI, SQRT_2};
use std::fs;

const R: f64 = 8.31446261815324; // J/(mol K)

#[derive(Debug, Clone, Deserialize)]
pub struct Component {
    pub name: String,
    pub tc: f64,
    pub pc: f64,
    pub omega: f64,
    pub molarweight: f64,
}

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
// Cubic equation solver (CORRECTED)
// =========================================================================

/// Solve PR cubic: Z^3 - (1-B)Z^2 + (A-3B^2-2B)Z - (AB-B^2-B^3) = 0
/// Returns sorted real roots with Z > B.
fn solve_cubic_pr(a_coeff: f64, b_coeff: f64) -> Vec<f64> {
    let c2 = -(1.0 - b_coeff);
    let c1 = a_coeff - 3.0 * b_coeff * b_coeff - 2.0 * b_coeff;
    let c0 = -(a_coeff * b_coeff - b_coeff * b_coeff - b_coeff.powi(3));

    // Depressed cubic t^3 + pt + q = 0 via z = t - c2/3
    let p = c1 - c2 * c2 / 3.0;
    let q = c0 - c1 * c2 / 3.0 + 2.0 * c2.powi(3) / 27.0;

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
        } else {
            // Fallback to trigonometric (near-triple-root)
            let r_val = (-p / 3.0).sqrt();
            let cos_arg = (-q / (2.0 * r_val.powi(3))).clamp(-1.0, 1.0);
            let theta = cos_arg.acos();
            let root = 2.0 * r_val * (theta / 3.0).cos() + shift;
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

fn fugacity_coeff_mix(
    t: f64,
    p: f64,
    comps: &[Component],
    x: &[f64],
    kij: &[Vec<f64>],
    idx: usize,
    vapor: bool,
) -> f64 {
    let n = comps.len();
    let a_vals: Vec<f64> = comps.iter().map(|c| pr_a(t, c)).collect();
    let b_vals: Vec<f64> = comps.iter().map(|c| pr_b(c)).collect();

    let mut a_mix = 0.0;
    let mut b_mix = 0.0;
    for i in 0..n {
        b_mix += x[i] * b_vals[i];
        for j in 0..n {
            a_mix +=
                x[i] * x[j] * (a_vals[i] * a_vals[j]).sqrt() * (1.0 - kij[i][j]);
        }
    }

    let big_a = a_mix * p / (R * R * t * t);
    let big_b = b_mix * p / (R * t);

    let roots = solve_cubic_pr(big_a, big_b);
    if roots.is_empty() {
        return 1.0;
    }
    let z = if vapor {
        *roots.last().unwrap()
    } else {
        *roots.first().unwrap()
    };

    let mut sum_aij = 0.0;
    for j in 0..n {
        sum_aij +=
            x[j] * (a_vals[idx] * a_vals[j]).sqrt() * (1.0 - kij[idx][j]);
    }
    let bi_bm = b_vals[idx] / b_mix;

    let ln_phi = bi_bm * (z - 1.0)
        - (z - big_b).ln()
        - big_a / (2.0 * SQRT_2 * big_b)
            * (2.0 * sum_aij / a_mix - bi_bm)
            * ((z + (1.0 + SQRT_2) * big_b)
                / (z + (1.0 - SQRT_2) * big_b))
                .ln();
    ln_phi.exp()
}

// =========================================================================
// Vapor pressure (pure component VLE)
// =========================================================================

fn vapor_pressure(t: f64, comp: &Component) -> f64 {
    // Wilson initial estimate
    let mut p =
        comp.pc * (5.37 * (1.0 + comp.omega) * (1.0 - comp.tc / t)).exp();
    if p < 1.0 {
        p = 1.0;
    }
    if p > comp.pc * 0.99 {
        p = comp.pc * 0.5;
    }

    for _ in 0..300 {
        let phi_l = fugacity_coeff_pure(t, p, comp, false);
        let phi_v = fugacity_coeff_pure(t, p, comp, true);
        let p_new = p * phi_l / phi_v;
        if ((p_new - p) / p).abs() < 1e-13 {
            return p_new;
        }
        p = p_new;
    }
    p
}

// =========================================================================
// Bubble-point pressure (mixture VLE)
// =========================================================================

fn bubble_point_pressure(
    t: f64,
    comps: &[Component],
    x: &[f64],
    kij: &[Vec<f64>],
) -> f64 {
    let n = comps.len();

    // Raoult initial estimate
    let psats: Vec<f64> = comps.iter().map(|c| vapor_pressure(t, c)).collect();
    let mut p: f64 = x.iter().enumerate().map(|(i, &xi)| xi * psats[i]).sum();

    // Wilson K-values for initial y
    let mut k_vals: Vec<f64> = comps
        .iter()
        .map(|c| (c.pc / p) * (5.37 * (1.0 + c.omega) * (1.0 - c.tc / t)).exp())
        .collect();
    let mut y: Vec<f64> = (0..n).map(|i| x[i] * k_vals[i]).collect();
    let sy: f64 = y.iter().sum();
    for yi in y.iter_mut() {
        *yi /= sy;
    }

    for _ in 0..500 {
        let mut sy_new = 0.0;
        let mut y_new = vec![0.0; n];
        for i in 0..n {
            let phi_l = fugacity_coeff_mix(t, p, comps, x, kij, i, false);
            let phi_v = fugacity_coeff_mix(t, p, comps, &y, kij, i, true);
            k_vals[i] = phi_l / phi_v;
            y_new[i] = x[i] * k_vals[i];
            sy_new += y_new[i];
        }
        let p_new = p * sy_new;
        for i in 0..n {
            y[i] = y_new[i] / sy_new;
        }
        if ((p_new - p) / p).abs() < 1e-11 {
            return p_new;
        }
        p = p_new;
    }
    p
}

// =========================================================================
// Dew-point pressure (mixture VLE)
// =========================================================================

fn dew_point_pressure(
    t: f64,
    comps: &[Component],
    y: &[f64],
    kij: &[Vec<f64>],
) -> f64 {
    let n = comps.len();

    // Initial estimate: 1/P = sum(yi/Psat_i)
    let psats: Vec<f64> = comps.iter().map(|c| vapor_pressure(t, c)).collect();
    let mut p: f64 =
        1.0 / y.iter().enumerate().map(|(i, &yi)| yi / psats[i]).sum::<f64>();

    // Wilson K-values for initial x
    let mut k_vals: Vec<f64> = comps
        .iter()
        .map(|c| (c.pc / p) * (5.37 * (1.0 + c.omega) * (1.0 - c.tc / t)).exp())
        .collect();
    let mut x: Vec<f64> = (0..n).map(|i| y[i] / k_vals[i]).collect();
    let sx: f64 = x.iter().sum();
    for xi in x.iter_mut() {
        *xi /= sx;
    }

    for _ in 0..500 {
        let mut sx_new = 0.0;
        let mut x_new = vec![0.0; n];
        for i in 0..n {
            let phi_l = fugacity_coeff_mix(t, p, comps, &x, kij, i, false);
            let phi_v = fugacity_coeff_mix(t, p, comps, y, kij, i, true);
            k_vals[i] = phi_l / phi_v;
            x_new[i] = y[i] / k_vals[i];
            sx_new += x_new[i];
        }
        let p_new = p / sx_new;
        for i in 0..n {
            x[i] = x_new[i] / sx_new;
        }
        if ((p_new - p) / p).abs() < 1e-11 {
            return p_new;
        }
        p = p_new;
    }
    p
}

// =========================================================================
// Isothermal flash
// =========================================================================

fn rachford_rice(beta: f64, z: &[f64], k: &[f64]) -> f64 {
    z.iter()
        .zip(k.iter())
        .map(|(&zi, &ki)| zi * (ki - 1.0) / (1.0 + beta * (ki - 1.0)))
        .sum()
}

fn rachford_rice_deriv(beta: f64, z: &[f64], k: &[f64]) -> f64 {
    z.iter()
        .zip(k.iter())
        .map(|(&zi, &ki)| {
            -zi * (ki - 1.0).powi(2) / (1.0 + beta * (ki - 1.0)).powi(2)
        })
        .sum()
}

fn flash_tp(
    t: f64,
    p: f64,
    comps: &[Component],
    z: &[f64],
    kij: &[Vec<f64>],
) -> (f64, Vec<f64>, Vec<f64>) {
    let n = comps.len();

    // Wilson K-values
    let mut k_vals: Vec<f64> = comps
        .iter()
        .map(|c| (c.pc / p) * (5.37 * (1.0 + c.omega) * (1.0 - c.tc / t)).exp())
        .collect();

    let mut beta = 0.5;
    let mut x_out = z.to_vec();
    let mut y_out = z.to_vec();

    for _ in 0..200 {
        // Check single-phase limits
        let g0 = rachford_rice(0.0, z, &k_vals);
        let g1 = rachford_rice(1.0, z, &k_vals);
        if g0 <= 0.0 {
            return (0.0, z.to_vec(), z.to_vec());
        }
        if g1 >= 0.0 {
            return (1.0, z.to_vec(), z.to_vec());
        }

        // Newton-Raphson for Rachford-Rice
        beta = 0.5;
        for _ in 0..100 {
            let f = rachford_rice(beta, z, &k_vals);
            if f.abs() < 1e-14 {
                break;
            }
            let df = rachford_rice_deriv(beta, z, &k_vals);
            let beta_new = beta - f / df;
            beta = beta_new.clamp(1e-12, 1.0 - 1e-12);
        }

        // Compositions
        let mut x: Vec<f64> = (0..n)
            .map(|i| z[i] / (1.0 + beta * (k_vals[i] - 1.0)))
            .collect();
        let mut y: Vec<f64> = (0..n).map(|i| k_vals[i] * x[i]).collect();
        let sx: f64 = x.iter().sum();
        let sy: f64 = y.iter().sum();
        for i in 0..n {
            x[i] /= sx;
            y[i] /= sy;
        }

        // Update K-values from fugacity coefficients
        let mut max_change = 0.0_f64;
        for i in 0..n {
            let phi_l = fugacity_coeff_mix(t, p, comps, &x, kij, i, false);
            let phi_v = fugacity_coeff_mix(t, p, comps, &y, kij, i, true);
            let k_new = phi_l / phi_v;
            let change = ((k_new - k_vals[i]) / k_vals[i]).abs();
            max_change = max_change.max(change);
            k_vals[i] = k_new;
        }

        x_out = x;
        y_out = y;

        if max_change < 1e-10 {
            break;
        }
    }

    (beta, x_out, y_out)
}

// =========================================================================
// Enthalpy departure and enthalpy of vaporization
// =========================================================================

fn enthalpy_departure(t: f64, p: f64, comp: &Component, vapor: bool) -> f64 {
    let a = pr_a(t, comp);
    let b = pr_b(comp);
    let ac = pr_ac(comp);
    let kap = pr_kappa(comp);
    let al = pr_alpha(t, comp);

    let big_a = a * p / (R * R * t * t);
    let big_b = b * p / (R * t);

    let roots = solve_cubic_pr(big_a, big_b);
    let z = if vapor {
        *roots.last().unwrap()
    } else {
        *roots.first().unwrap()
    };

    // T*da/dT - a = -ac*(1+kappa)*sqrt(alpha)
    let coeff = -ac * (1.0 + kap) * al.sqrt();
    let log_term = ((z + (1.0 + SQRT_2) * big_b)
        / (z + (1.0 - SQRT_2) * big_b))
        .ln();

    R * t * (z - 1.0) + coeff / (b * 2.0 * SQRT_2) * log_term
}

fn enthalpy_of_vaporization(t: f64, comp: &Component) -> f64 {
    let psat = vapor_pressure(t, comp);
    let h_v = enthalpy_departure(t, psat, comp, true);
    let h_l = enthalpy_departure(t, psat, comp, false);
    h_v - h_l
}

// =========================================================================
// Liquid compressibility factor at saturation
// =========================================================================

fn z_liquid_at_saturation(t: f64, comp: &Component) -> f64 {
    let psat = vapor_pressure(t, comp);
    let a = pr_a(t, comp);
    let b = pr_b(comp);
    let big_a = a * psat / (R * R * t * t);
    let big_b = b * psat / (R * t);
    let roots = solve_cubic_pr(big_a, big_b);
    *roots.first().unwrap() // smallest root = liquid
}

// =========================================================================
// Residual isochoric heat capacity
// =========================================================================

fn cv_residual(t: f64, p: f64, comp: &Component, vapor: bool) -> f64 {
    let a_val = pr_a(t, comp);
    let b = pr_b(comp);
    let ac = pr_ac(comp);
    let kap = pr_kappa(comp);
    let al = pr_alpha(t, comp);

    let big_a = a_val * p / (R * R * t * t);
    let big_b = b * p / (R * t);

    let roots = solve_cubic_pr(big_a, big_b);
    let z = if vapor {
        *roots.last().unwrap()
    } else {
        *roots.first().unwrap()
    };

    // d^2 a / dT^2 = ac * kappa / (2*T) * (kappa/Tc + sqrt(alpha)/sqrt(T*Tc))
    let d2a_dt2 =
        ac * kap / (2.0 * t) * (kap / comp.tc + al.sqrt() / (t * comp.tc).sqrt());

    let log_term = ((z + (1.0 + SQRT_2) * big_b)
        / (z + (1.0 - SQRT_2) * big_b))
        .ln();

    t * d2a_dt2 / (2.0 * SQRT_2 * b) * log_term
}

// =========================================================================
// Main
// =========================================================================

fn main() {
    let data =
        fs::read_to_string("/app/data/components.json").expect("Failed to read components.json");
    let components: Vec<Component> =
        serde_json::from_str(&data).expect("Failed to parse JSON");

    let propane = components
        .iter()
        .find(|c| c.name == "propane")
        .unwrap()
        .clone();
    let butane = components
        .iter()
        .find(|c| c.name == "butane")
        .unwrap()
        .clone();
    let pentane = components
        .iter()
        .find(|c| c.name == "pentane")
        .unwrap()
        .clone();

    let kij_2 = vec![vec![0.0; 2]; 2];
    let kij_3 = vec![vec![0.0; 3]; 3];

    let propane_psat = vapor_pressure(300.0, &propane);
    let butane_psat = vapor_pressure(350.0, &butane);

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

    let (flash_beta, flash_x, flash_y) = flash_tp(
        300.0,
        250000.0,
        &[propane.clone(), butane.clone(), pentane.clone()],
        &[0.2, 0.3, 0.5],
        &kij_3,
    );

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
