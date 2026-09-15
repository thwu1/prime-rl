#!/usr/bin/env python3
"""ONERA OAT15A transonic buffet analysis.

Processes experimental Cp distributions and pressure PSDs from Tecplot ASCII
format files. Produces shock characterization, section loads, spectral
analysis, buffet onset determination, gnuplot plots, and Tecplot summary.

"""

import json
import csv
import os
import subprocess
import sys
import numpy as np

# ── Flow conditions ──────────────────────────────────────────────────────────
MACH = 0.73
T_STATIC = 271.0       # K
GAMMA = 1.4
R_AIR = 287.058         # J/(kg·K)
CHORD = 0.230           # m (230 mm)
RE_C = 3.0e6

A_INF = np.sqrt(GAMMA * R_AIR * T_STATIC)   # speed of sound
U_INF = MACH * A_INF                         # freestream velocity


# ── Tecplot I/O ──────────────────────────────────────────────────────────────

def parse_tecplot(filepath):
    """Parse a multi-zone Tecplot ASCII file and return (variables, zones)."""
    zones = []
    variables = []
    cur = None

    with open(filepath) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            if line.upper().startswith('VARIABLES'):
                rest = line.split('=', 1)[1]
                variables = [
                    s.strip('" ') for s in rest.split('"')
                    if s.strip('" ,')
                ]
                continue

            if line.upper().startswith('ZONE'):
                if cur is not None:
                    zones.append(cur)
                title = line.split('"')[1] if '"' in line else ''
                cur = {'title': title, 'rows': []}
                continue

            if cur is not None:
                try:
                    cur['rows'].append([float(v) for v in line.split()])
                except ValueError:
                    pass

        if cur is not None:
            zones.append(cur)

    return variables, zones


def alpha_from_title(title):
    """Extract angle of attack from zone title 'M = 0.73 - a = X.XX'."""
    for segment in reversed(title.split('a')):
        if '=' in segment:
            try:
                return float(segment.split('=')[-1].strip())
            except ValueError:
                continue
    return 0.0


# ── Surface processing ───────────────────────────────────────────────────────

def split_surfaces(xc, cp):
    """Split concatenated upper+lower Cp data.

    In the raw Tecplot zone the upper surface runs LE→TE (x/c 0→1)
    and the lower surface follows TE→LE. The split is at the trailing
    edge, i.e. the maximum x/c value.
    """
    te = int(np.argmax(xc))
    xu, cpu = xc[:te + 1].copy(), cp[:te + 1].copy()
    xl, cpl = xc[te + 1:].copy()[::-1], cp[te + 1:].copy()[::-1]
    return xu, cpu, xl, cpl


def shock_location(xu, cpu):
    """Locate the normal shock on the upper surface.

    Returns (x_shock, delta_cp) where x_shock is the midpoint of the
    steepest positive Cp gradient interval and delta_cp is the pressure
    jump magnitude.
    """
    dx = np.diff(xu)
    dcp = np.diff(cpu)
    grad = np.where(dx > 0, dcp / dx, 0.0)

    # Restrict to x/c > 0.15 to skip the leading-edge suction peak
    mask = xu[:-1] > 0.15
    grad_masked = np.where(mask, grad, -np.inf)

    idx = int(np.argmax(grad_masked))
    x_sh = 0.5 * (xu[idx] + xu[idx + 1])
    d_cp = float(abs(cpu[idx + 1] - cpu[idx]))
    return x_sh, d_cp


def section_coefficients(xu, cpu, xl, cpl):
    """Compute Cl and Cm about the quarter-chord by pressure integration.

    Cl  = ∫(Cp_l − Cp_u) d(x/c)
    Cm_LE = −∫(Cp_l − Cp_u)·(x/c) d(x/c)
    Cm_qc = Cm_LE + Cl/4
    """
    int_u = float(np.trapz(cpu, xu))
    int_l = float(np.trapz(cpl, xl))
    cl = int_l - int_u

    mom_u = float(np.trapz(cpu * xu, xu))
    mom_l = float(np.trapz(cpl * xl, xl))
    cm_le = mom_u - mom_l         # = −∫ΔCp·(x/c) d(x/c)
    cm_qc = cm_le + 0.25 * cl

    return cl, cm_qc


# ── Spectral analysis ────────────────────────────────────────────────────────

def spectral_features(freq, psd):
    """Extract dominant frequency, Strouhal number, and narrowband fraction.

    Searches the 30–200 Hz band for the PSD peak (buffet frequency).
    Narrowband fraction is computed relative to the 10–300 Hz analysis band.
    """
    f, p = freq[1:], psd[1:]          # skip DC

    band = (f >= 30) & (f <= 200)
    if not np.any(band):
        return 0.0, 0.0, 0.0, 0.0

    idx_band = np.where(band)[0]
    pk = idx_band[int(np.argmax(p[band]))]
    f_dom = float(f[pk])
    psd_pk = float(p[pk])

    st = f_dom * CHORD / U_INF

    # Energy in ±15 Hz around peak vs 10–300 Hz band
    aband = (f >= 10) & (f <= 300)
    total_e = float(np.trapz(p[aband], f[aband])) if np.any(aband) else 1.0

    nb = (f >= f_dom - 15) & (f <= f_dom + 15)
    nb_e = float(np.trapz(p[nb], f[nb])) if np.any(nb) else 0.0
    nb_frac = nb_e / total_e if total_e > 0 else 0.0

    return f_dom, st, psd_pk, nb_frac


def onset_from_spectra(records):
    """Determine buffet onset from the evolution of spectral peaks.

    Identifies the first consecutive pair of angles where the PSD peak
    amplitude jumps by more than an order of magnitude.
    """
    records = sorted(records, key=lambda r: r['alpha'])
    alphas = [r['alpha'] for r in records]
    peaks = [r['psd_peak'] for r in records]

    onset = alphas[-1]
    for i in range(1, len(peaks)):
        if peaks[i - 1] > 0 and peaks[i] / peaks[i - 1] > 10:
            onset = 0.5 * (alphas[i - 1] + alphas[i])
            break

    classify = {}
    for a in alphas:
        classify[f"{a:.2f}"] = "pre-buffet" if a < onset else "buffet"

    return onset, classify


# ── Gnuplot output ───────────────────────────────────────────────────────────

COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']


def write_gnuplot_cp(cp_recs, outpng):
    d = os.path.dirname(outpng)
    os.makedirs(d, exist_ok=True)

    datafiles = []
    for i, rec in enumerate(cp_recs):
        uf = os.path.join(d, f'cp_u{i}.dat')
        lf = os.path.join(d, f'cp_l{i}.dat')
        with open(uf, 'w') as fh:
            for x, c in zip(rec['xu'], rec['cpu']):
                fh.write(f'{x:.6f} {c:.6f}\n')
        with open(lf, 'w') as fh:
            for x, c in zip(rec['xl'], rec['cpl']):
                fh.write(f'{x:.6f} {c:.6f}\n')
        datafiles.append((rec['alpha'], uf, lf, COLORS[i % len(COLORS)]))

    cmds = []
    for alpha, uf, lf, col in datafiles:
        cmds.append(
            f"'{uf}' u 1:2 w lp lc rgb '{col}' pt 7 ps 0.5 "
            f"t 'a={alpha} upper'"
        )
        cmds.append(
            f"'{lf}' u 1:2 w lp lc rgb '{col}' pt 5 ps 0.5 "
            f"t 'a={alpha} lower'"
        )

    script = (
        f"set terminal pngcairo size 1200,800 enhanced font 'Arial,12'\n"
        f"set output '{outpng}'\n"
        "set xlabel 'x/c'\n"
        "set ylabel 'C_p'\n"
        "set yrange [] reverse\n"
        "set title 'ONERA OAT15A - Surface Pressure Distributions (M=0.73)'\n"
        "set key right bottom\n"
        "set grid\n"
        "plot " + ", \\\n     ".join(cmds) + "\n"
    )

    gp = os.path.join(d, 'cp_overlay.gp')
    with open(gp, 'w') as fh:
        fh.write(script)
    subprocess.run(['gnuplot', gp], check=True)


def write_gnuplot_psd(sp_recs, outpng):
    d = os.path.dirname(outpng)
    os.makedirs(d, exist_ok=True)

    datafiles = []
    for i, rec in enumerate(sp_recs):
        datf = os.path.join(d, f'psd_{i}.dat')
        with open(datf, 'w') as fh:
            for ff, pp in zip(rec['freq'], rec['psd']):
                if ff > 0:
                    fh.write(f'{ff:.4f} {pp:.6e}\n')
        datafiles.append((rec['alpha'], datf, COLORS[i % len(COLORS)]))

    cmds = []
    for alpha, datf, col in datafiles:
        cmds.append(
            f"'{datf}' u 1:2 w l lw 2 lc rgb '{col}' t 'a={alpha}'"
        )

    script = (
        f"set terminal pngcairo size 1200,800 enhanced font 'Arial,12'\n"
        f"set output '{outpng}'\n"
        "set xlabel 'Frequency (Hz)'\n"
        "set ylabel 'PSD (Pa^2/Hz)'\n"
        "set title 'ONERA OAT15A - Pressure PSD (M=0.73)'\n"
        "set key right top\n"
        "set grid\n"
        "set logscale y\n"
        "set xrange [0:500]\n"
        "plot " + ", \\\n     ".join(cmds) + "\n"
    )

    gp = os.path.join(d, 'psd_comparison.gp')
    with open(gp, 'w') as fh:
        fh.write(script)
    subprocess.run(['gnuplot', gp], check=True)


# ── Tecplot summary output ───────────────────────────────────────────────────

def write_tecplot_summary(combined, outfile):
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    with open(outfile, 'w') as fh:
        fh.write('TITLE = "OAT15A Buffet Analysis"\n')
        fh.write('VARIABLES = "ALPHA" "CL" "CM_QC" "X_SHOCK" '
                 '"DELTA_CP" "F_BUFFET" "STROUHAL"\n')
        fh.write(f'ZONE T="M=0.73 Rec=3e6" I={len(combined)}, F=POINT\n')
        for r in combined:
            fh.write(
                f" {r['alpha']:8.4f} {r['cl']:12.8f} {r['cm_qc']:12.8f}"
                f" {r['x_shock']:8.4f} {r['delta_cp']:8.4f}"
                f" {r['f_dom']:8.3f} {r['st']:10.6f}\n"
            )


# ── Main pipeline ────────────────────────────────────────────────────────────

def main():
    os.makedirs('/app/results', exist_ok=True)
    os.makedirs('/app/plots', exist_ok=True)

    _, cp_zones = parse_tecplot('/app/data/cp_distributions.dat')
    _, sp_zones = parse_tecplot('/app/data/pressure_spectra.dat')

    shocks = []
    loads = []
    spec_recs = []
    cp_recs = []
    sp_recs = []
    combined = []

    for cpz, spz in zip(cp_zones, sp_zones):
        alpha = alpha_from_title(cpz['title'])

        # ── Cp processing ──
        arr = np.array(cpz['rows'])
        xc, cp = arr[:, 0], arr[:, 1]
        xu, cpu, xl, cpl = split_surfaces(xc, cp)
        xs, dcp = shock_location(xu, cpu)
        cl, cmqc = section_coefficients(xu, cpu, xl, cpl)

        # ── Spectral processing ──
        spa = np.array(spz['rows'])
        freq, psd = spa[:, 0], spa[:, 1]
        fd, st, ppk, nbf = spectral_features(freq, psd)

        shocks.append({
            'alpha': alpha, 'x_shock': round(xs, 5),
            'delta_cp': round(dcp, 5),
        })
        loads.append({
            'alpha': alpha, 'cl': round(cl, 6),
            'cm_qc': round(cmqc, 6),
        })
        spec_recs.append({
            'alpha': alpha, 'f_dominant_hz': round(fd, 3),
            'strouhal': round(st, 6), 'psd_peak': round(ppk, 2),
            'narrowband_fraction': round(nbf, 6),
        })
        cp_recs.append({
            'alpha': alpha, 'xu': xu, 'cpu': cpu,
            'xl': xl, 'cpl': cpl,
        })
        sp_recs.append({'alpha': alpha, 'freq': freq, 'psd': psd})
        combined.append({
            'alpha': alpha, 'cl': cl, 'cm_qc': cmqc,
            'x_shock': xs, 'delta_cp': dcp, 'f_dom': fd, 'st': st,
        })

    # ── Buffet onset ──
    onset, classify = onset_from_spectra(spec_recs)

    # ── Write CSVs ──
    with open('/app/results/shock_positions.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['alpha', 'x_shock', 'delta_cp'])
        w.writeheader()
        w.writerows(shocks)

    with open('/app/results/section_loads.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['alpha', 'cl', 'cm_qc'])
        w.writeheader()
        w.writerows(loads)

    with open('/app/results/spectral_analysis.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=[
            'alpha', 'f_dominant_hz', 'strouhal',
            'psd_peak', 'narrowband_fraction',
        ])
        w.writeheader()
        w.writerows(spec_recs)

    with open('/app/results/buffet_onset.json', 'w') as fh:
        json.dump({
            'onset_alpha_deg': round(onset, 2),
            'classification': classify,
            'mach': MACH,
            'reynolds': RE_C,
            'chord_m': CHORD,
        }, fh, indent=2)

    # ── Plots ──
    write_gnuplot_cp(cp_recs, '/app/plots/cp_overlay.png')
    write_gnuplot_psd(sp_recs, '/app/plots/psd_comparison.png')

    # ── Tecplot summary ──
    write_tecplot_summary(combined, '/app/results/summary.tec')

    # ── Report ──
    print('Analysis complete.')
    for r in combined:
        print(f"  a={r['alpha']:5.2f}: Cl={r['cl']:.4f} Cm={r['cm_qc']:.4f} "
              f"x_sh={r['x_shock']:.3f} f={r['f_dom']:.1f}Hz St={r['st']:.4f}")
    print(f"  Buffet onset: a={onset:.2f} deg")


if __name__ == '__main__':
    main()
