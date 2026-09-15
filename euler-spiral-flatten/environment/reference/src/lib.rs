//! Euler spiral curve flattening — reference implementation.
//!
//! Derived from production GPU 2D renderer algorithms.
//! Uses f64 for numerical compatibility with Python.

use std::f64::consts::FRAC_PI_4;

const TANGENT_THRESH: f64 = 1e-6;
const DERIV_THRESH: f64 = 1e-6;
const DERIV_EPS: f64 = 1e-6;
const SUBDIV_LIMIT: f64 = 1.0 / 65536.0;

const BREAK1: f64 = 0.8;
const BREAK2: f64 = 1.25;
const BREAK3: f64 = 2.1;
const SIN_SCALE: f64 = 1.0976991822760038;
const QUAD_A1: f64 = 0.6406;
const QUAD_B1: f64 = -0.81;
const QUAD_C1: f64 = 0.9148117935952064;
const QUAD_A2: f64 = 0.5;
const QUAD_B2: f64 = -0.156;
const QUAD_C2: f64 = 0.16145779359520596;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Vec2 {
    pub x: f64,
    pub y: f64,
}

impl Vec2 {
    pub fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }

    pub fn length_squared(self) -> f64 {
        self.x * self.x + self.y * self.y
    }

    pub fn length(self) -> f64 {
        self.length_squared().sqrt()
    }

    pub fn atan2(self) -> f64 {
        self.y.atan2(self.x)
    }
}

impl std::ops::Add for Vec2 {
    type Output = Self;
    fn add(self, rhs: Self) -> Self {
        Self::new(self.x + rhs.x, self.y + rhs.y)
    }
}

impl std::ops::Sub for Vec2 {
    type Output = Self;
    fn sub(self, rhs: Self) -> Self {
        Self::new(self.x - rhs.x, self.y - rhs.y)
    }
}

impl std::ops::Mul<f64> for Vec2 {
    type Output = Self;
    fn mul(self, s: f64) -> Self {
        Self::new(self.x * s, self.y * s)
    }
}

/// Integrate Euler spiral using 10th-order polynomial approximation.
///
/// Approximates the Fresnel-like integrals of exp(i*(k0*t + 0.5*k1*t^2)) dt
/// integrated from -0.5 to 0.5. Uses a product-of-sums expansion where
/// subscripts i_j denote total power i and minimum power j in k0 and k1.
pub fn integ_euler_10(k0: f64, k1: f64) -> (f64, f64) {
    let t1_1 = k0;
    let t1_2 = 0.5 * k1;
    let t2_2 = t1_1 * t1_1;
    let t2_3 = 2.0 * (t1_1 * t1_2);
    let t2_4 = t1_2 * t1_2;
    let t3_4 = t2_2 * t1_2 + t2_3 * t1_1;
    let t3_6 = t2_4 * t1_2;
    let t4_4 = t2_2 * t2_2;
    let t4_5 = 2.0 * (t2_2 * t2_3);
    let t4_6 = 2.0 * (t2_2 * t2_4) + t2_3 * t2_3;
    let t4_7 = 2.0 * (t2_3 * t2_4);
    let t4_8 = t2_4 * t2_4;
    let t5_6 = t4_4 * t1_2 + t4_5 * t1_1;
    let t5_8 = t4_6 * t1_2 + t4_7 * t1_1;
    let t6_6 = t4_4 * t2_2;
    let t6_7 = t4_4 * t2_3 + t4_5 * t2_2;
    let t6_8 = t4_4 * t2_4 + t4_5 * t2_3 + t4_6 * t2_2;
    let t7_8 = t6_6 * t1_2 + t6_7 * t1_1;
    let t8_8 = t6_6 * t2_2;

    let mut u = 1.0;
    u -= (1.0 / 24.0) * t2_2 + (1.0 / 160.0) * t2_4;
    u += (1.0 / 1920.0) * t4_4 + (1.0 / 10752.0) * t4_6 + (1.0 / 55296.0) * t4_8;
    u -= (1.0 / 322560.0) * t6_6 + (1.0 / 1658880.0) * t6_8;
    u += (1.0 / 92897280.0) * t8_8;

    let mut v = (1.0 / 12.0) * t1_2;
    v -= (1.0 / 480.0) * t3_4 + (1.0 / 2688.0) * t3_6;
    v += (1.0 / 53760.0) * t5_6 + (1.0 / 276480.0) * t5_8;
    v -= (1.0 / 11612160.0) * t7_8;

    (u, v)
}

/// Parameters defining a normalized Euler spiral segment.
pub struct EulerParams {
    pub th0: f64,
    pub k0: f64,
    pub k1: f64,
    pub ch: f64,
}

impl EulerParams {
    /// Compute Euler spiral parameters from endpoint tangent angles.
    ///
    /// k0 = th0 + th1 (exact). k1 and ch are computed via polynomial
    /// approximations calibrated for accuracy up to ~1 radian.
    pub fn from_angles(th0: f64, th1: f64) -> Self {
        let k0 = th0 + th1;
        let dth = th1 - th0;
        let d2 = dth * dth;
        let k2 = k0 * k0;

        let mut a = 6.0;
        a -= d2 * (1.0 / 70.0);
        a -= (d2 * d2) * (1.0 / 10780.0);
        a += (d2 * d2 * d2) * 2.769178184818219e-07;
        let b = -0.1 + d2 * (1.0 / 4200.0) + d2 * d2 * 1.6959677820260655e-05;
        let c = -1.0 / 1400.0 + d2 * 6.84915970574303e-05 - k2 * 7.936475029053326e-06;
        a += (b + c * k2) * k2;
        let k1 = dth * a;

        let mut ch = 1.0;
        ch -= d2 * (1.0 / 40.0);
        ch += (d2 * d2) * 0.00034226190482569864;
        ch -= (d2 * d2 * d2) * 1.9349474568904524e-06;
        let b2 = -1.0 / 24.0 + d2 * 0.0024702380951963226 - d2 * d2 * 3.7297408997537985e-05;
        let c2 = 1.0 / 1920.0 - d2 * 4.87350869747975e-05 - k2 * 3.1001936068463107e-06;
        ch += (b2 + c2 * k2) * k2;

        Self { th0, k0, k1, ch }
    }

    /// Evaluate tangent angle at parameter t in [0, 1].
    pub fn eval_th(&self, t: f64) -> f64 {
        (self.k0 + 0.5 * self.k1 * (t - 1.0)) * t - self.th0
    }

    /// Evaluate point on normalized Euler spiral at parameter t.
    pub fn eval(&self, t: f64) -> Vec2 {
        let thm = self.eval_th(t * 0.5);
        let k0 = self.k0;
        let k1 = self.k1;
        let (u, v) = integ_euler_10((k0 + k1 * (0.5 * t - 0.5)) * t, k1 * t * t);
        let s = t / self.ch * thm.sin();
        let c = t / self.ch * thm.cos();
        let x = u * c - v * s;
        let y = -v * c - u * s;
        Vec2::new(x, y)
    }

    /// Evaluate point on offset curve.
    pub fn eval_with_offset(&self, t: f64, offset: f64) -> Vec2 {
        let th = self.eval_th(t);
        let ov = Vec2::new(offset * th.sin(), offset * th.cos());
        let base = self.eval(t);
        Vec2::new(base.x + ov.x, base.y + ov.y)
    }
}

/// An Euler spiral segment mapped to world coordinates.
pub struct EulerSeg {
    pub p0: Vec2,
    pub p1: Vec2,
    pub params: EulerParams,
}

impl EulerSeg {
    pub fn eval_with_offset(&self, t: f64, normalized_offset: f64) -> Vec2 {
        let chord = self.p1 - self.p0;
        let pt = self.params.eval_with_offset(t, normalized_offset);
        Vec2::new(
            self.p0.x + chord.x * pt.x - chord.y * pt.y,
            self.p0.y + chord.x * pt.y + chord.y * pt.x,
        )
    }
}

/// Parameters derived from a cubic Bézier for Euler spiral fitting.
pub struct CubicParams {
    pub th0: f64,
    pub th1: f64,
    pub chord_len: f64,
    pub err: f64,
}

impl CubicParams {
    /// Compute parameters from endpoints and derivative vectors.
    ///
    /// Handles near-zero chord (degenerate case), near-cusp, and
    /// general case robustly. Error estimation uses an empirical formula
    /// calibrated against Fréchet distance.
    pub fn from_points_derivs(p0: Vec2, p1: Vec2, q0: Vec2, q1: Vec2, dt: f64) -> Self {
        let chord = p1 - p0;
        let chord_squared = chord.length_squared();
        let chord_len = chord_squared.sqrt();

        if chord_squared < TANGENT_THRESH * TANGENT_THRESH {
            let chord_err =
                ((9.0 / 32.0) * (q0.length_squared() + q1.length_squared())).sqrt() * dt;
            return Self {
                th0: 0.0,
                th1: 0.0,
                chord_len: TANGENT_THRESH,
                err: chord_err,
            };
        }

        let scale = dt / chord_squared;
        let h0 = Vec2::new(
            q0.x * chord.x + q0.y * chord.y,
            q0.y * chord.x - q0.x * chord.y,
        );
        let th0 = h0.atan2();
        let d0 = h0.length() * scale;
        let h1 = Vec2::new(
            q1.x * chord.x + q1.y * chord.y,
            q1.x * chord.y - q1.y * chord.x,
        );
        let th1 = h1.atan2();
        let d1 = h1.length() * scale;

        let cth0 = th0.cos();
        let cth1 = th1.cos();
        let mut err = if cth0 * cth1 < 0.0 {
            // Near-cusp case
            2.0
        } else {
            let e0 = (2.0 / 3.0) / (1.0 + cth0).max(1e-9);
            let e1 = (2.0 / 3.0) / (1.0 + cth1).max(1e-9);
            let s0 = th0.sin();
            let s1 = th1.sin();
            let s01 = cth0 * s1 + cth1 * s0;
            let amin = 0.15 * (2.0 * e0 * s0 + 2.0 * e1 * s1 - e0 * e1 * s01);
            let a = 0.15 * (2.0 * d0 * s0 + 2.0 * d1 * s1 - d0 * d1 * s01);
            let aerr = (a - amin).abs();
            let symm = (th0 + th1).abs();
            let asymm = (th0 - th1).abs();
            let dist = (d0 - e0).hypot(d1 - e1);
            let ctr = 4.625e-6 * symm.powi(5) + 7.5e-3 * asymm * symm.powi(2);
            let halo_symm = 5e-3 * symm * dist;
            let halo_asymm = 7e-2 * asymm * dist;
            ctr + 1.55 * aerr + halo_symm + halo_asymm
        };
        err *= chord_len;
        Self {
            th0,
            th1,
            chord_len,
            err,
        }
    }
}

/// Piecewise approximation of the ESPC integral.
///
/// Odd function, monotonically increasing. Uses different approximation
/// strategies in different regions of the domain.
pub fn espc_int_approx(x: f64) -> f64 {
    let y = x.abs();
    let a = if y < BREAK1 {
        (SIN_SCALE * y).sin() * (1.0 / SIN_SCALE)
    } else if y < BREAK2 {
        (8.0_f64.sqrt() / 3.0) * (y - 1.0) * (y - 1.0).abs().sqrt() + FRAC_PI_4
    } else {
        let (qa, qb, qc) = if y < BREAK3 {
            (QUAD_A1, QUAD_B1, QUAD_C1)
        } else {
            (QUAD_A2, QUAD_B2, QUAD_C2)
        };
        qa * y * y + qb * y + qc
    };
    a.copysign(x)
}

/// Piecewise approximation of the inverse ESPC integral.
///
/// Functional inverse of espc_int_approx.
pub fn espc_int_inv_approx(x: f64) -> f64 {
    let y = x.abs();
    let a = if y < 0.7010707591262915 {
        (y * SIN_SCALE).asin() * (1.0 / SIN_SCALE)
    } else if y < 0.903249293595206 {
        let b = y - FRAC_PI_4;
        let u = b.abs().powf(2.0 / 3.0).copysign(b);
        u * (9.0_f64 / 8.0).cbrt() + 1.0
    } else {
        let (u_val, v_val, w) = if y < 2.038857793595206 {
            let bb = 0.5 * QUAD_B1 / QUAD_A1;
            (bb * bb - QUAD_C1 / QUAD_A1, 1.0 / QUAD_A1, bb)
        } else {
            let bb = 0.5 * QUAD_B2 / QUAD_A2;
            (bb * bb - QUAD_C2 / QUAD_A2, 1.0 / QUAD_A2, bb)
        };
        (u_val + v_val * y).sqrt() - w
    };
    a.copysign(x)
}

/// Evaluate cubic Bézier point and derivative at parameter t.
///
/// The derivative q(t) is NOT multiplied by 3.
pub fn eval_cubic_and_deriv(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, t: f64) -> (Vec2, Vec2) {
    let m = 1.0 - t;
    let mm = m * m;
    let mt = m * t;
    let tt = t * t;
    let p = p0 * (mm * m) + (p1 * (3.0 * mm) + p2 * (3.0 * mt) + p3 * tt) * t;
    let q = (p1 - p0) * mm + (p2 - p1) * (2.0 * mt) + (p3 - p2) * tt;
    (p, q)
}

fn trailing_zeros(n: u32) -> u32 {
    if n == 0 {
        0
    } else {
        n.trailing_zeros()
    }
}

/// Flatten a cubic Bézier curve into a polyline (fill mode, offset=0).
pub fn flatten_cubic(
    p0: Vec2,
    p1: Vec2,
    p2: Vec2,
    p3: Vec2,
    tolerance: f64,
) -> Vec<(f64, f64)> {
    if p0 == p1 && p0 == p2 && p0 == p3 {
        return vec![(p0.x, p0.y)];
    }

    let tol = tolerance;
    let frac_1_sqrt_2: f64 = 1.0 / 2.0_f64.sqrt();
    let mut result = vec![(p0.x, p0.y)];

    let mut t0_u: u32 = 0;
    let mut dt: f64 = 1.0;
    let mut last_p = p0;
    let mut last_q = p1 - p0;
    if last_q.length_squared() < DERIV_THRESH * DERIV_THRESH {
        last_q = eval_cubic_and_deriv(p0, p1, p2, p3, DERIV_EPS).1;
    }
    let mut last_t: f64 = 0.0;

    loop {
        let t0 = (t0_u as f64) * dt;
        if t0 >= 1.0 {
            break;
        }

        let mut t1 = t0 + dt;
        let this_p0 = last_p;
        let this_q0 = last_q;
        let (mut this_p1, mut this_q1) = eval_cubic_and_deriv(p0, p1, p2, p3, t1);

        if this_q1.length_squared() < DERIV_THRESH * DERIV_THRESH {
            let (new_p1, new_q1) = eval_cubic_and_deriv(p0, p1, p2, p3, t1 - DERIV_EPS);
            this_q1 = new_q1;
            if t1 < 1.0 {
                this_p1 = new_p1;
                t1 -= DERIV_EPS;
            }
        }

        let actual_dt = t1 - last_t;
        let cubic_params =
            CubicParams::from_points_derivs(this_p0, this_p1, this_q0, this_q1, actual_dt);

        if cubic_params.err <= tol || dt <= SUBDIV_LIMIT {
            let euler_params = EulerParams::from_angles(cubic_params.th0, cubic_params.th1);
            let es = EulerSeg {
                p0: this_p0,
                p1: this_p1,
                params: euler_params,
            };

            let k0_shifted = es.params.k0 - 0.5 * es.params.k1;
            let k1_val = es.params.k1;

            // Fill mode: offset = 0
            let normalized_offset: f64 = 0.0;
            let dist_scaled: f64 = 0.0;

            const K1_THRESH: f64 = 1e-3;
            const DIST_THRESH: f64 = 1e-3;

            let mut a_espc: f64 = 0.0;
            let mut b_espc: f64 = 0.0;
            let mut integral: f64 = 0.0;
            let mut int0: f64 = 0.0;

            #[derive(Clone, Copy)]
            enum Robust {
                LowK1,
                LowDist,
                Normal,
            }

            let (n_frac, robust) = if k1_val.abs() < K1_THRESH {
                let k = k0_shifted + 0.5 * k1_val;
                let n_frac = (k * (k * dist_scaled + 1.0)).abs().sqrt();
                (n_frac, Robust::LowK1)
            } else if dist_scaled.abs() < DIST_THRESH {
                let f = |x: f64| x * x.abs().sqrt();
                a_espc = k1_val;
                b_espc = k0_shifted;
                int0 = f(b_espc);
                let int1 = f(a_espc + b_espc);
                integral = int1 - int0;
                let n_frac = if a_espc.abs() > 1e-12 {
                    (2.0 / 3.0) * integral / a_espc
                } else {
                    0.0
                };
                (n_frac, Robust::LowDist)
            } else {
                a_espc = -2.0 * dist_scaled * k1_val;
                b_espc = -1.0 - 2.0 * dist_scaled * k0_shifted;
                int0 = espc_int_approx(b_espc);
                let int1 = espc_int_approx(a_espc + b_espc);
                integral = int1 - int0;
                let k_peak = if a_espc.abs() > 1e-12 {
                    k0_shifted - k1_val * b_espc / a_espc
                } else {
                    k0_shifted
                };
                let integrand_peak =
                    (k_peak * (k_peak * dist_scaled + 1.0)).abs().sqrt();
                let n_frac = if a_espc.abs() > 1e-12 {
                    integral * integrand_peak / a_espc
                } else {
                    0.0
                };
                (n_frac, Robust::Normal)
            };

            let ch_safe = es.params.ch.abs().max(1e-12);
            let scale_multiplier =
                0.5 * frac_1_sqrt_2 * (cubic_params.chord_len / (ch_safe * tol)).max(0.0).sqrt();

            let n = (n_frac.abs() * scale_multiplier)
                .ceil()
                .clamp(1.0, 100.0) as usize;

            for i in 0..n {
                let lp1 = if i == n - 1 && t1 >= 1.0 {
                    (p3.x, p3.y)
                } else {
                    let t_param = (i + 1) as f64 / n as f64;
                    let s = match robust {
                        Robust::LowK1 => t_param,
                        Robust::LowDist => {
                            let c_val = integral * t_param + int0;
                            let c_cbrt = if c_val.abs() < 1e-30 {
                                0.0
                            } else {
                                c_val.abs().powf(1.0 / 3.0).copysign(c_val)
                            };
                            let inv = c_cbrt * c_cbrt.abs();
                            if a_espc.abs() > 1e-12 {
                                (inv - b_espc) / a_espc
                            } else {
                                t_param
                            }
                        }
                        Robust::Normal => {
                            let inv = espc_int_inv_approx(integral * t_param + int0);
                            if a_espc.abs() > 1e-12 {
                                (inv - b_espc) / a_espc
                            } else {
                                t_param
                            }
                        }
                    };
                    let s_clamped = s.clamp(0.0, 1.0);
                    let pt = es.eval_with_offset(s_clamped, normalized_offset);
                    (pt.x, pt.y)
                };
                result.push(lp1);
            }

            last_p = this_p1;
            last_q = this_q1;
            last_t = t1;

            t0_u += 1;
            let shift = trailing_zeros(t0_u);
            t0_u >>= shift;
            dt *= (1u32 << shift) as f64;
        } else {
            t0_u = t0_u.saturating_mul(2);
            dt *= 0.5;
        }
    }

    result
}
