#!/usr/bin/env python3
"""Generate synthetic CMS-format dimuon event data using only standard library."""
import random
import math
import csv
import os


def main():
    random.seed(42)
    N = 50000
    M_MU = 0.10566  # muon mass in GeV

    # Resonances: (mass_GeV, detector_resolution_sigma_GeV, yield)
    resonances = [
        (0.775, 0.014, 1500),
        (1.019, 0.016, 1200),
        (3.097, 0.047, 4000),
        (3.686, 0.056, 300),
        (9.460, 0.140, 1500),
        (10.023, 0.148, 700),
        (10.355, 0.153, 300),
        (91.188, 2.95, 2000),
    ]

    n_signal = sum(y for _, _, y in resonances)
    n_bkg = N - n_signal

    # Build list of (invariant_mass, is_signal)
    event_specs = []

    # Background: power-law dN/dM ~ M^{-2} in [0.25, 150] GeV
    # Inverse CDF: M = 1/(1/M_min - U*(1/M_min - 1/M_max))
    M_min, M_max = 0.25, 150.0
    inv_min, inv_max = 1.0 / M_min, 1.0 / M_max
    for _ in range(n_bkg):
        u = random.random()
        m = 1.0 / (inv_min - u * (inv_min - inv_max))
        event_specs.append((m, False))

    # Signal: Gaussian peaks at resonance masses
    for peak_mass, sigma, yield_n in resonances:
        for _ in range(yield_n):
            m = random.gauss(peak_mass, sigma)
            m = max(m, 2 * M_MU + 0.001)
            event_specs.append((m, True))

    # Shuffle all events
    random.shuffle(event_specs)

    run_choices = [146436, 147196, 148002, 148822, 149291]

    os.makedirs('/app/data', exist_ok=True)
    outpath = '/app/data/dimuon_events.csv'

    nan_count = 0
    same_charge_count = 0

    with open(outpath, 'w', newline='') as f:
        writer = csv.writer(f)
        # Note: 'px1 ' has trailing space, matching real CMS dimuon CSV quirk
        writer.writerow([
            'Run', 'Event', 'Type1', 'E1', 'px1 ', 'py1', 'pz1',
            'pt1', 'eta1', 'phi1', 'Q1',
            'Type2', 'E2', 'px2', 'py2', 'pz2',
            'pt2', 'eta2', 'phi2', 'Q2', 'M'
        ])

        for mass, is_sig in event_specs:
            # NaN injection (~0.5% of events)
            inject_nan = random.random() < 0.005

            # --- Generate 4-vectors via Lorentz boost ---
            E_star = mass / 2.0
            p_star = math.sqrt(max(E_star ** 2 - M_MU ** 2, 1e-12))

            # Random direction in pair CM frame
            cos_theta = random.uniform(-1.0, 1.0)
            sin_theta = math.sqrt(max(1.0 - cos_theta ** 2, 0.0))
            phi_cm = random.uniform(0.0, 2.0 * math.pi)

            px1_cm = p_star * sin_theta * math.cos(phi_cm)
            py1_cm = p_star * sin_theta * math.sin(phi_cm)
            pz1_cm = p_star * cos_theta

            # Pair lab-frame kinematics
            pt_pair = random.expovariate(0.2)  # mean = 5.0
            y_pair = random.gauss(0.0, 1.5)
            phi_pair = random.uniform(0.0, 2.0 * math.pi)

            mt_pair = math.sqrt(mass ** 2 + pt_pair ** 2)
            E_pair = mt_pair * math.cosh(y_pair)
            pz_pair = mt_pair * math.sinh(y_pair)
            px_pair = pt_pair * math.cos(phi_pair)
            py_pair = pt_pair * math.sin(phi_pair)

            # Boost velocity
            beta_x = px_pair / E_pair
            beta_y = py_pair / E_pair
            beta_z = pz_pair / E_pair
            beta_sq = beta_x ** 2 + beta_y ** 2 + beta_z ** 2
            gamma = 1.0 / math.sqrt(max(1.0 - beta_sq, 1e-14))

            # Boost muon 1 (p_cm -> lab)
            bdotp1 = beta_x * px1_cm + beta_y * py1_cm + beta_z * pz1_cm
            if beta_sq > 1e-14:
                coeff1 = (gamma - 1.0) * bdotp1 / beta_sq + gamma * E_star
            else:
                coeff1 = E_star
            E1 = gamma * (E_star + bdotp1)
            px1 = px1_cm + beta_x * coeff1
            py1 = py1_cm + beta_y * coeff1
            pz1 = pz1_cm + beta_z * coeff1

            # Boost muon 2 (-p_cm -> lab)
            bdotp2 = -bdotp1
            if beta_sq > 1e-14:
                coeff2 = (gamma - 1.0) * bdotp2 / beta_sq + gamma * E_star
            else:
                coeff2 = E_star
            E2 = gamma * (E_star + bdotp2)
            px2 = -px1_cm + beta_x * coeff2
            py2 = -py1_cm + beta_y * coeff2
            pz2 = -pz1_cm + beta_z * coeff2

            # Detector momentum smearing (2% per muon)
            scale1 = 1.0 + random.gauss(0.0, 0.02)
            scale2 = 1.0 + random.gauss(0.0, 0.02)
            px1 *= scale1; py1 *= scale1; pz1 *= scale1
            px2 *= scale2; py2 *= scale2; pz2 *= scale2

            # Recompute energies from smeared momenta (on-shell constraint)
            E1 = math.sqrt(px1 ** 2 + py1 ** 2 + pz1 ** 2 + M_MU ** 2)
            E2 = math.sqrt(px2 ** 2 + py2 ** 2 + pz2 ** 2 + M_MU ** 2)

            # Derived quantities
            pt1 = math.sqrt(px1 ** 2 + py1 ** 2)
            pt2 = math.sqrt(px2 ** 2 + py2 ** 2)
            p1_mag = math.sqrt(px1 ** 2 + py1 ** 2 + pz1 ** 2)
            p2_mag = math.sqrt(px2 ** 2 + py2 ** 2 + pz2 ** 2)
            eps = 1e-10
            eta1 = 0.5 * math.log((p1_mag + pz1 + eps) / (p1_mag - pz1 + eps))
            eta2 = 0.5 * math.log((p2_mag + pz2 + eps) / (p2_mag - pz2 + eps))
            phi1_val = math.atan2(py1, px1)
            phi2_val = math.atan2(py2, px2)

            # Invariant mass from smeared 4-vectors
            M_inv = math.sqrt(max(
                (E1 + E2) ** 2 - (px1 + px2) ** 2
                - (py1 + py2) ** 2 - (pz1 + pz2) ** 2, 0.0))

            # Charges
            q1, q2 = 1, -1
            if not is_sig and random.random() < 0.15:
                q2 = 1
                same_charge_count += 1
            flip = random.choice([-1, 1])
            q1 *= flip; q2 *= flip

            # Muon types: G(lobal)=70%, T(racker)=25%, S(tandalone)=5%
            r1 = random.random()
            type1 = 'G' if r1 < 0.70 else ('T' if r1 < 0.95 else 'S')
            r2 = random.random()
            type2 = 'G' if r2 < 0.70 else ('T' if r2 < 0.95 else 'S')

            # Run / Event numbers
            run_n = random.choice(run_choices)
            event_n = random.randint(10000000, 99999999)

            if inject_nan:
                nan_count += 1
                writer.writerow([
                    run_n, event_n, type1,
                    float('nan'), float('nan'), float('nan'), float('nan'),
                    float('nan'), float('nan'), float('nan'), q1,
                    type2,
                    float('nan'), float('nan'), float('nan'), float('nan'),
                    float('nan'), float('nan'), float('nan'), q2,
                    float('nan')
                ])
            else:
                writer.writerow([
                    run_n, event_n, type1,
                    round(E1, 7), round(px1, 7), round(py1, 7), round(pz1, 7),
                    round(pt1, 7), round(eta1, 7), round(phi1_val, 7), q1,
                    type2,
                    round(E2, 7), round(px2, 7), round(py2, 7), round(pz2, 7),
                    round(pt2, 7), round(eta2, 7), round(phi2_val, 7), q2,
                    round(M_inv, 7)
                ])

    print(f"Generated {N} events -> {outpath}")
    print(f"  Signal events: {n_signal}")
    print(f"  Background events: {n_bkg}")
    print(f"  NaN events: {nan_count}")
    print(f"  Same-charge events: {same_charge_count}")


if __name__ == '__main__':
    main()
