#!/usr/bin/env python3
"""
filterspec — Elliptic filter specification, analysis, and plotting tool.

Subcommands:
  analyze        Analyze a reference JSON and print filter characteristics
  export-zpk     Export ZPK from the elliptic_filter module to a JSON file
  bode-script    Generate gnuplot script + frequency response data file
  pipeline       Full pipeline: export all configs -> generate gnuplot -> render SVGs

Run 'python3 tools/filterspec.py <subcommand> --help' for details.
"""

import argparse
import json
import os
import sys
import subprocess

import numpy as np


def cmd_analyze(args):
    """Analyze a reference JSON file and print filter characteristics."""
    with open(args.ref_file) as f:
        ref = json.load(f)

    N = ref["filter_order"]
    rp = ref["passband_ripple_dB"]
    rs = ref["stopband_attenuation_dB"]
    n_z = ref.get("n_zeros_expected", "?")
    n_p = ref.get("n_poles_expected", "?")

    eps_sq = 10 ** (rp / 10.0) - 1.0
    eps = eps_sq ** 0.5
    k1_sq = eps_sq / (10 ** (rs / 10.0) - 1.0)

    print(f"Filter specification: N={N}, rp={rp} dB, rs={rs} dB")
    print(f"  Topology:                  {n_p} poles, {n_z} zeros")
    print(f"  Ripple factor (epsilon):   {eps:.6f}")
    print(f"  Selectivity (k1^2):        {k1_sq:.6e}")
    print(f"  Passband edge gain:        {10**(-rp/20):.6f} ({-rp:.1f} dB)")
    print(f"  Stopband ceiling:          {10**(-rs/20):.6e} ({-rs:.1f} dB)")

    if "frequency_response_samples" in ref:
        samples = ref["frequency_response_samples"]
        print(f"  Frequency response samples: {len(samples)} points")

    poles = ref.get("poles", [])
    if poles:
        print(f"  Pole locations:")
        for i, (re_p, im_p) in enumerate(poles):
            mag = (re_p ** 2 + im_p ** 2) ** 0.5
            print(f"    p[{i}] = {re_p:+.8f} {im_p:+.8f}j  (|p|={mag:.6f})")

    zeros = ref.get("zeros", [])
    if zeros:
        print(f"  Zero locations:")
        for i, (re_z, im_z) in enumerate(zeros):
            print(f"    z[{i}] = {re_z:+.8f} {im_z:+.8f}j")

    if "gain" in ref:
        print(f"  Gain: {ref['gain']:.10e}")


def cmd_export_zpk(args):
    """Export ZPK data from the filter implementation to a JSON file."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from elliptic_filter import elliptic_filter_design

    z, p, k = elliptic_filter_design(args.order, args.rp, args.rs)
    z = [complex(zi) for zi in z]
    p = [complex(pi) for pi in p]

    data = {
        "order": args.order,
        "passband_ripple_dB": args.rp,
        "stopband_attenuation_dB": args.rs,
        "zeros_real": [float(np.real(zi)) for zi in z],
        "zeros_imag": [float(np.imag(zi)) for zi in z],
        "poles_real": [float(np.real(pi)) for pi in p],
        "poles_imag": [float(np.imag(pi)) for pi in p],
        "gain": float(k),
    }

    outdir = os.path.dirname(args.output)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Exported ZPK -> {args.output}")


def _compute_freq_response(zpk_data, n_points=1000, w_min=0.01, w_max=10.0):
    """Compute |H(jw)| in dB from ZPK data over a log frequency sweep."""
    zr = zpk_data["zeros_real"]
    zi = zpk_data["zeros_imag"]
    pr = zpk_data["poles_real"]
    pi_v = zpk_data["poles_imag"]
    gain = zpk_data["gain"]

    z_arr = [complex(r, i) for r, i in zip(zr, zi)]
    p_arr = [complex(r, i) for r, i in zip(pr, pi_v)]

    omegas = np.logspace(np.log10(w_min), np.log10(w_max), n_points)
    rows = []
    for w in omegas:
        s = 1j * w
        num = gain
        for zz in z_arr:
            num *= (s - zz)
        den = 1.0
        for pp in p_arr:
            den *= (s - pp)
        mag = abs(num / den)
        mag_db = 20 * np.log10(max(mag, 1e-100))
        rows.append((float(w), float(mag_db)))
    return rows


def cmd_bode_script(args):
    """Generate a gnuplot script and data file for Bode magnitude plot."""
    with open(args.zpk_file) as f:
        zpk = json.load(f)

    N = zpk["order"]
    rp = zpk["passband_ripple_dB"]
    rs = zpk["stopband_attenuation_dB"]

    svg_out = args.svg if args.svg else args.output.replace(".gp", ".svg")
    dat_out = args.output.replace(".gp", ".dat")

    # Compute frequency response
    rows = _compute_freq_response(
        zpk, n_points=args.samples, w_min=args.xmin, w_max=args.xmax
    )
    outdir = os.path.dirname(dat_out)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(dat_out, "w") as f:
        for w, mag_db in rows:
            f.write(f"{w},{mag_db}\n")
    print(f"  Data file -> {dat_out}")

    ymin = -int(rs) - 20

    gp = (
        f'set terminal svg size 800,500 enhanced font "Arial,12"\n'
        f'set output "{svg_out}"\n'
        f'set title "Elliptic Filter Bode Plot  N={N}  rp={rp}dB  rs={rs}dB"\n'
        f'set xlabel "Frequency (rad/s)"\n'
        f'set ylabel "Magnitude (dB)"\n'
        f"set grid\n"
        f"set logscale x\n"
        f"set xrange [{args.xmin}:{args.xmax}]\n"
        f"set yrange [{ymin}:5]\n"
        f'set datafile separator ","\n'
        f'set arrow from {args.xmin},-{rp} to 1,-{rp} nohead dashtype 2 lc rgb "blue"\n'
        f'set arrow from 1,-{rs} to {args.xmax},-{rs} nohead dashtype 2 lc rgb "red"\n'
        f'set label "passband (-{rp}dB)" at 0.02,{-rp+2} font "Arial,9" tc rgb "blue"\n'
        f'set label "stopband (-{rs}dB)" at 2,{-rs+3} font "Arial,9" tc rgb "red"\n'
        f'plot "{dat_out}" using 1:2 with lines lw 2 lc rgb "black" title "|H(jw)|"\n'
    )

    with open(args.output, "w") as f:
        f.write(gp)
    print(f"  Script   -> {args.output}")
    print(f"  Run: gnuplot {args.output}")


def cmd_pipeline(args):
    """Full pipeline: export ZPK, generate gnuplot scripts, render SVGs."""
    import glob as globmod

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    ref_files = sorted(globmod.glob(os.path.join(args.configs, "*.json")))
    if not ref_files:
        print(f"ERROR: no reference JSON files in {args.configs}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)
    errors = []

    for ref_file in ref_files:
        with open(ref_file) as f:
            ref = json.load(f)

        N = ref["filter_order"]
        rp = ref["passband_ripple_dB"]
        rs = ref["stopband_attenuation_dB"]
        base = os.path.splitext(os.path.basename(ref_file))[0]

        print(f"\n=== {base} (N={N}, rp={rp}, rs={rs}) ===")

        zpk_path = os.path.join(args.output, f"{base}.zpk")
        gp_path = os.path.join(args.output, f"{base}.gp")
        dat_path = os.path.join(args.output, f"{base}.dat")
        svg_path = os.path.join(args.output, f"{base}.svg")

        # Step 1: Export ZPK
        try:
            from elliptic_filter import elliptic_filter_design
            z, p, k = elliptic_filter_design(N, rp, rs)
            zpk_data = {
                "order": N,
                "passband_ripple_dB": rp,
                "stopband_attenuation_dB": rs,
                "zeros_real": [float(np.real(zi)) for zi in z],
                "zeros_imag": [float(np.imag(zi)) for zi in z],
                "poles_real": [float(np.real(pi)) for pi in p],
                "poles_imag": [float(np.imag(pi)) for pi in p],
                "gain": float(k),
            }
            with open(zpk_path, "w") as f:
                json.dump(zpk_data, f, indent=2)
            print(f"  ZPK  -> {zpk_path}")
        except Exception as e:
            errors.append(f"{base}: ZPK export failed -- {e}")
            continue

        # Step 2: Compute frequency response data
        rows = _compute_freq_response(zpk_data)
        with open(dat_path, "w") as f:
            for w, mag_db in rows:
                f.write(f"{w},{mag_db}\n")
        print(f"  Data -> {dat_path}")

        # Step 3: Generate gnuplot script
        ymin = -int(rs) - 20
        gp_content = (
            f'set terminal svg size 800,500 enhanced font "Arial,12"\n'
            f'set output "{svg_path}"\n'
            f'set title "Elliptic Filter Bode Plot  N={N}  rp={rp}dB  rs={rs}dB"\n'
            f'set xlabel "Frequency (rad/s)"\n'
            f'set ylabel "Magnitude (dB)"\n'
            f"set grid\n"
            f"set logscale x\n"
            f"set xrange [0.01:10]\n"
            f"set yrange [{ymin}:5]\n"
            f'set datafile separator ","\n'
            f'set arrow from 0.01,-{rp} to 1,-{rp} nohead dashtype 2 lc rgb "blue"\n'
            f'set arrow from 1,-{rs} to 10,-{rs} nohead dashtype 2 lc rgb "red"\n'
            f'plot "{dat_path}" using 1:2 with lines lw 2 lc rgb "black" title "|H(jw)|"\n'
        )
        with open(gp_path, "w") as f:
            f.write(gp_content)
        print(f"  GP   -> {gp_path}")

        # Step 4: Run gnuplot
        try:
            result = subprocess.run(
                ["gnuplot", gp_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                errors.append(f"{base}: gnuplot error -- {result.stderr.strip()}")
            else:
                print(f"  SVG  -> {svg_path}")
        except FileNotFoundError:
            errors.append(
                f"{base}: gnuplot not found -- install with: apt-get install gnuplot-nox"
            )
        except subprocess.TimeoutExpired:
            errors.append(f"{base}: gnuplot timed out")

    print(f"\n{'=' * 60}")
    if errors:
        print(f"PIPELINE FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"  * {e}")
        sys.exit(1)
    else:
        print("PIPELINE COMPLETE -- all SVGs generated")


def main():
    parser = argparse.ArgumentParser(
        prog="filterspec",
        description="Elliptic filter specification, analysis, and plotting tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s analyze reference_data/order5_rp1.0_rs40.json
  %(prog)s export-zpk 5 1.0 40.0 --output output/order5.zpk
  %(prog)s bode-script output/order5.zpk --output output/order5.gp
  gnuplot output/order5.gp
  %(prog)s pipeline --configs reference_data/ --output output/
""",
    )
    sub = parser.add_subparsers(dest="cmd")

    # analyze
    p_an = sub.add_parser("analyze", help="Analyze a reference JSON file")
    p_an.add_argument("ref_file", help="Path to reference JSON")

    # export-zpk
    p_ex = sub.add_parser(
        "export-zpk", help="Export ZPK data from elliptic_filter implementation"
    )
    p_ex.add_argument("order", type=int, help="Filter order N")
    p_ex.add_argument("rp", type=float, help="Passband ripple (dB)")
    p_ex.add_argument("rs", type=float, help="Stopband attenuation (dB)")
    p_ex.add_argument("--output", required=True, help="Output .zpk JSON file")

    # bode-script
    p_bs = sub.add_parser(
        "bode-script", help="Generate gnuplot Bode plot script + data"
    )
    p_bs.add_argument("zpk_file", help="Input .zpk JSON file")
    p_bs.add_argument("--output", required=True, help="Output .gp script file")
    p_bs.add_argument(
        "--svg", default=None, help="SVG output path (default: .gp -> .svg)"
    )
    p_bs.add_argument(
        "--samples", type=int, default=1000, help="Number of frequency points (default: 1000)"
    )
    p_bs.add_argument(
        "--xmin", type=float, default=0.01, help="Min frequency (default: 0.01)"
    )
    p_bs.add_argument(
        "--xmax", type=float, default=10.0, help="Max frequency (default: 10.0)"
    )

    # pipeline
    p_pl = sub.add_parser(
        "pipeline", help="Full export -> gnuplot -> SVG pipeline for all configs"
    )
    p_pl.add_argument(
        "--configs", required=True, help="Directory with reference JSON files"
    )
    p_pl.add_argument(
        "--output", required=True, help="Output directory for ZPK, scripts, SVGs"
    )

    args = parser.parse_args()
    if args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "export-zpk":
        cmd_export_zpk(args)
    elif args.cmd == "bode-script":
        cmd_bode_script(args)
    elif args.cmd == "pipeline":
        cmd_pipeline(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
