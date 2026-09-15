"""Complete Euler spiral curve flattening implementation.

Ported from Vello's CPU reference shaders (euler.rs and flatten.rs).
"""

import math
from geometry import Vec2

# Robustness thresholds
TANGENT_THRESH = 1e-6
DERIV_THRESH = 1e-6
DERIV_EPS = 1e-6
SUBDIV_LIMIT = 1.0 / 65536.0

# ESPC integral breakpoints and coefficients
BREAK1 = 0.8
BREAK2 = 1.25
BREAK3 = 2.1
SIN_SCALE = 1.0976991822760038
QUAD_A1 = 0.6406
QUAD_B1 = -0.81
QUAD_C1 = 0.9148117935952064
QUAD_A2 = 0.5
QUAD_B2 = -0.156
QUAD_C2 = 0.16145779359520596
FRAC_PI_4 = math.pi / 4.0


def integ_euler_10(k0, k1):
    """10th-order polynomial Euler spiral integration.

    Intermediate terms use product-of-sums expansion. The subscripts i_j
    denote total power i and minimum power j in k0 and k1.
    """
    t1_1 = k0
    t1_2 = 0.5 * k1
    t2_2 = t1_1 * t1_1
    t2_3 = 2.0 * (t1_1 * t1_2)
    t2_4 = t1_2 * t1_2
    t3_4 = t2_2 * t1_2 + t2_3 * t1_1
    t3_6 = t2_4 * t1_2
    t4_4 = t2_2 * t2_2
    t4_5 = 2.0 * (t2_2 * t2_3)
    t4_6 = 2.0 * (t2_2 * t2_4) + t2_3 * t2_3
    t4_7 = 2.0 * (t2_3 * t2_4)
    t4_8 = t2_4 * t2_4
    t5_6 = t4_4 * t1_2 + t4_5 * t1_1
    t5_8 = t4_6 * t1_2 + t4_7 * t1_1
    t6_6 = t4_4 * t2_2
    t6_7 = t4_4 * t2_3 + t4_5 * t2_2
    t6_8 = t4_4 * t2_4 + t4_5 * t2_3 + t4_6 * t2_2
    t7_8 = t6_6 * t1_2 + t6_7 * t1_1
    t8_8 = t6_6 * t2_2

    u = 1.0
    u -= (1.0 / 24.0) * t2_2 + (1.0 / 160.0) * t2_4
    u += (1.0 / 1920.0) * t4_4 + (1.0 / 10752.0) * t4_6 + (1.0 / 55296.0) * t4_8
    u -= (1.0 / 322560.0) * t6_6 + (1.0 / 1658880.0) * t6_8
    u += (1.0 / 92897280.0) * t8_8

    v = (1.0 / 12.0) * t1_2
    v -= (1.0 / 480.0) * t3_4 + (1.0 / 2688.0) * t3_6
    v += (1.0 / 53760.0) * t5_6 + (1.0 / 276480.0) * t5_8
    v -= (1.0 / 11612160.0) * t7_8

    return (u, v)


class EulerParams:
    def __init__(self, th0, k0, k1, ch):
        self.th0 = th0
        self.k0 = k0
        self.k1 = k1
        self.ch = ch

    @classmethod
    def from_angles(cls, th0, th1):
        k0 = th0 + th1
        dth = th1 - th0
        d2 = dth * dth
        k2 = k0 * k0

        # Polynomial for k1
        a = 6.0
        a -= d2 * (1.0 / 70.0)
        a -= (d2 * d2) * (1.0 / 10780.0)
        a += (d2 * d2 * d2) * 2.769178184818219e-07
        b = -0.1 + d2 * (1.0 / 4200.0) + d2 * d2 * 1.6959677820260655e-05
        c = -1.0 / 1400.0 + d2 * 6.84915970574303e-05 - k2 * 7.936475029053326e-06
        a += (b + c * k2) * k2
        k1 = dth * a

        # Polynomial for normalized chord length
        ch = 1.0
        ch -= d2 * (1.0 / 40.0)
        ch += (d2 * d2) * 0.00034226190482569864
        ch -= (d2 * d2 * d2) * 1.9349474568904524e-06
        b2 = -1.0 / 24.0 + d2 * 0.0024702380951963226 - d2 * d2 * 3.7297408997537985e-05
        c2 = 1.0 / 1920.0 - d2 * 4.87350869747975e-05 - k2 * 3.1001936068463107e-06
        ch += (b2 + c2 * k2) * k2

        return cls(th0, k0, k1, ch)

    def eval_th(self, t):
        return (self.k0 + 0.5 * self.k1 * (t - 1.0)) * t - self.th0

    def eval(self, t):
        thm = self.eval_th(t * 0.5)
        k0 = self.k0
        k1 = self.k1
        u, v = integ_euler_10((k0 + k1 * (0.5 * t - 0.5)) * t, k1 * t * t)
        s = t / self.ch * math.sin(thm)
        c = t / self.ch * math.cos(thm)
        x = u * c - v * s
        y = -v * c - u * s
        return Vec2(x, y)

    def eval_with_offset(self, t, offset):
        th = self.eval_th(t)
        ov = Vec2(offset * math.sin(th), offset * math.cos(th))
        return self.eval(t) + ov


class EulerSeg:
    def __init__(self, p0, p1, params):
        self.p0 = p0
        self.p1 = p1
        self.params = params

    def eval_with_offset(self, t, normalized_offset):
        chord = self.p1 - self.p0
        pt = self.params.eval_with_offset(t, normalized_offset)
        return Vec2(
            self.p0.x + chord.x * pt.x - chord.y * pt.y,
            self.p0.y + chord.x * pt.y + chord.y * pt.x,
        )


class CubicParams:
    def __init__(self, th0, th1, chord_len, err):
        self.th0 = th0
        self.th1 = th1
        self.chord_len = chord_len
        self.err = err

    @classmethod
    def from_points_derivs(cls, p0, p1, q0, q1, dt):
        chord = p1 - p0
        chord_squared = chord.length_squared()
        chord_len = math.sqrt(chord_squared)

        if chord_squared < TANGENT_THRESH ** 2:
            chord_err = math.sqrt(
                (9.0 / 32.0) * (q0.length_squared() + q1.length_squared())
            ) * dt
            return cls(0.0, 0.0, TANGENT_THRESH, chord_err)

        scale = dt / chord_squared
        h0 = Vec2(
            q0.x * chord.x + q0.y * chord.y,
            q0.y * chord.x - q0.x * chord.y,
        )
        th0 = h0.atan2()
        d0 = h0.length() * scale
        h1 = Vec2(
            q1.x * chord.x + q1.y * chord.y,
            q1.x * chord.y - q1.y * chord.x,
        )
        th1 = h1.atan2()
        d1 = h1.length() * scale

        cth0 = math.cos(th0)
        cth1 = math.cos(th1)

        if cth0 * cth1 < 0.0:
            err = 2.0
        else:
            e0 = (2.0 / 3.0) / max(1.0 + cth0, 1e-9)
            e1 = (2.0 / 3.0) / max(1.0 + cth1, 1e-9)
            s0 = math.sin(th0)
            s1 = math.sin(th1)
            s01 = cth0 * s1 + cth1 * s0
            amin = 0.15 * (2.0 * e0 * s0 + 2.0 * e1 * s1 - e0 * e1 * s01)
            a_val = 0.15 * (2.0 * d0 * s0 + 2.0 * d1 * s1 - d0 * d1 * s01)
            aerr = abs(a_val - amin)
            symm = abs(th0 + th1)
            asymm = abs(th0 - th1)
            dist = math.hypot(d0 - e0, d1 - e1)
            ctr = 4.625e-6 * symm ** 5 + 7.5e-3 * asymm * symm ** 2
            halo_symm = 5e-3 * symm * dist
            halo_asymm = 7e-2 * asymm * dist
            err = ctr + 1.55 * aerr + halo_symm + halo_asymm

        err *= chord_len
        return cls(th0, th1, chord_len, err)


def espc_int_approx(x):
    y = abs(x)
    if y < BREAK1:
        a = math.sin(SIN_SCALE * y) * (1.0 / SIN_SCALE)
    elif y < BREAK2:
        a = (math.sqrt(8.0) / 3.0) * (y - 1.0) * math.sqrt(abs(y - 1.0)) + FRAC_PI_4
    else:
        if y < BREAK3:
            qa, qb, qc = QUAD_A1, QUAD_B1, QUAD_C1
        else:
            qa, qb, qc = QUAD_A2, QUAD_B2, QUAD_C2
        a = qa * y * y + qb * y + qc
    return math.copysign(a, x)


def espc_int_inv_approx(x):
    y = abs(x)
    if y < 0.7010707591262915:
        a = math.asin(y * SIN_SCALE) * (1.0 / SIN_SCALE)
    elif y < 0.903249293595206:
        b = y - FRAC_PI_4
        u = math.copysign(abs(b) ** (2.0 / 3.0), b)
        a = u * (9.0 / 8.0) ** (1.0 / 3.0) + 1.0
    else:
        if y < 2.038857793595206:
            B = 0.5 * QUAD_B1 / QUAD_A1
            u_val = B * B - QUAD_C1 / QUAD_A1
            v_val = 1.0 / QUAD_A1
            w = B
        else:
            B = 0.5 * QUAD_B2 / QUAD_A2
            u_val = B * B - QUAD_C2 / QUAD_A2
            v_val = 1.0 / QUAD_A2
            w = B
        a = math.sqrt(u_val + v_val * y) - w
    return math.copysign(a, x)


def eval_cubic_and_deriv(p0, p1, p2, p3, t):
    m = 1.0 - t
    mm = m * m
    mt = m * t
    tt = t * t
    p = p0 * (mm * m) + (p1 * (3.0 * mm) + p2 * (3.0 * mt) + p3 * tt) * t
    q = (p1 - p0) * mm + (p2 - p1) * (2.0 * mt) + (p3 - p2) * tt
    return (p, q)


def _trailing_zeros(n):
    """Count trailing zeros of positive integer n."""
    if n == 0:
        return 0
    count = 0
    while (n & 1) == 0:
        count += 1
        n >>= 1
    return count


def flatten_cubic(p0, p1, p2, p3, tolerance=0.25):
    # Degenerate: all points identical
    if p0 == p1 and p0 == p2 and p0 == p3:
        return [(p0.x, p0.y)]

    tol = tolerance
    result = [(p0.x, p0.y)]

    t0_u = 0
    dt = 1.0
    last_p = p0
    last_q = p1 - p0
    if last_q.length_squared() < DERIV_THRESH ** 2:
        _, last_q = eval_cubic_and_deriv(p0, p1, p2, p3, DERIV_EPS)
    last_t = 0.0

    while True:
        t0 = t0_u * dt
        if t0 >= 1.0:
            break

        t1 = t0 + dt
        this_p0 = last_p
        this_q0 = last_q
        this_p1, this_q1 = eval_cubic_and_deriv(p0, p1, p2, p3, t1)

        if this_q1.length_squared() < DERIV_THRESH ** 2:
            new_p1, new_q1 = eval_cubic_and_deriv(p0, p1, p2, p3, t1 - DERIV_EPS)
            this_q1 = new_q1
            if t1 < 1.0:
                this_p1 = new_p1
                t1 -= DERIV_EPS

        actual_dt = t1 - last_t
        cubic_params = CubicParams.from_points_derivs(
            this_p0, this_p1, this_q0, this_q1, actual_dt
        )

        if cubic_params.err <= tol or dt <= SUBDIV_LIMIT:
            euler_params = EulerParams.from_angles(cubic_params.th0, cubic_params.th1)
            es = EulerSeg(this_p0, this_p1, euler_params)

            # Shifted curvature for ESPC
            k0_shifted = es.params.k0 - 0.5 * es.params.k1
            k1_val = es.params.k1

            # Fill mode: offset = 0
            normalized_offset = 0.0
            dist_scaled = 0.0

            K1_THRESH = 1e-3
            DIST_THRESH = 1e-3

            a_espc = 0.0
            b_espc = 0.0
            integral = 0.0
            int0 = 0.0

            if abs(k1_val) < K1_THRESH:
                k = k0_shifted + 0.5 * k1_val
                n_frac = math.sqrt(abs(k * (k * dist_scaled + 1.0)))
                robust = 'LowK1'
            elif abs(dist_scaled) < DIST_THRESH:
                def f_pow15(x):
                    return x * math.sqrt(abs(x))
                a_espc = k1_val
                b_espc = k0_shifted
                int0 = f_pow15(b_espc)
                int1 = f_pow15(a_espc + b_espc)
                integral = int1 - int0
                n_frac = (2.0 / 3.0) * integral / a_espc if abs(a_espc) > 1e-12 else 0.0
                robust = 'LowDist'
            else:
                a_espc = -2.0 * dist_scaled * k1_val
                b_espc = -1.0 - 2.0 * dist_scaled * k0_shifted
                int0 = espc_int_approx(b_espc)
                int1 = espc_int_approx(a_espc + b_espc)
                integral = int1 - int0
                k_peak = k0_shifted - k1_val * b_espc / a_espc if abs(a_espc) > 1e-12 else k0_shifted
                integrand_peak = math.sqrt(abs(k_peak * (k_peak * dist_scaled + 1.0)))
                n_frac = integral * integrand_peak / a_espc if abs(a_espc) > 1e-12 else 0.0
                robust = 'Normal'

            ch_safe = max(abs(es.params.ch), 1e-12)
            scale_multiplier = (
                0.5
                * (1.0 / math.sqrt(2.0))
                * math.sqrt(max(cubic_params.chord_len / (ch_safe * tol), 0.0))
            )

            n = max(1, min(100, int(math.ceil(abs(n_frac) * scale_multiplier))))

            for i in range(n):
                if i == n - 1 and t1 >= 1.0:
                    lp1 = (p3.x, p3.y)
                else:
                    t_param = (i + 1) / n
                    if robust == 'LowK1':
                        s = t_param
                    elif robust == 'LowDist':
                        c_val = integral * t_param + int0
                        if abs(c_val) < 1e-30:
                            c_cbrt = 0.0
                        else:
                            c_cbrt = math.copysign(abs(c_val) ** (1.0 / 3.0), c_val)
                        inv = c_cbrt * abs(c_cbrt)
                        s = (inv - b_espc) / a_espc if abs(a_espc) > 1e-12 else t_param
                    else:
                        inv = espc_int_inv_approx(integral * t_param + int0)
                        s = (inv - b_espc) / a_espc if abs(a_espc) > 1e-12 else t_param

                    s = max(0.0, min(1.0, s))
                    pt = es.eval_with_offset(s, normalized_offset)
                    lp1 = (pt.x, pt.y)

                result.append(lp1)

            last_p = this_p1
            last_q = this_q1
            last_t = t1

            t0_u += 1
            shift = _trailing_zeros(t0_u)
            t0_u >>= shift
            dt *= (1 << shift)
        else:
            t0_u *= 2
            dt *= 0.5

    return result
