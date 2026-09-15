#!/usr/bin/env python3

"""CLI for Figge-Fencl v3.0 acid-base model."""

import argparse
import json
import math
import sys

sys.path.insert(0, '/app')

from figge_fencl import (
    predict_pH,
    albumin_charge,
    albumin_net_charge_per_mol,
    phosphate_charge,
    hco3,
)


def cmd_predict_ph(args):
    pH = predict_pH(args.sid, args.pco2, args.pi, args.alb)
    print(json.dumps({"pH": round(pH, 6)}))


def cmd_validate(args):
    data = []
    with open(args.data) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            data.append({
                'sample': int(parts[0]),
                'pH_measured': float(parts[1]),
                'SID': float(parts[2]),
                'PCO2': float(parts[3]),
                'Pi': float(parts[4]),
                'Albumin': float(parts[5])
            })

    results = []
    sq_errors = []
    abs_errors = []
    measured = []
    predicted = []

    for d in data:
        pred = predict_pH(d['SID'], d['PCO2'], d['Pi'], d['Albumin'])
        err = pred - d['pH_measured']
        results.append({
            'sample': d['sample'],
            'pH_measured': d['pH_measured'],
            'pH_predicted': round(pred, 6),
            'error': round(err, 6)
        })
        sq_errors.append(err ** 2)
        abs_errors.append(abs(err))
        measured.append(d['pH_measured'])
        predicted.append(pred)

    n = len(data)
    rmse = math.sqrt(sum(sq_errors) / n)
    mad = sum(abs_errors) / n
    max_abs = max(abs_errors)

    mean_m = sum(measured) / n
    ss_tot = sum((m - mean_m) ** 2 for m in measured)
    ss_res = sum(sq_errors)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    print(json.dumps({
        'n_samples': n,
        'rmse': round(rmse, 6),
        'mad': round(mad, 6),
        'max_abs_error': round(max_abs, 6),
        'r_squared': round(r_squared, 6),
        'results': results
    }))


def cmd_analyze(args):
    SIDa = args.na + args.k + 2 * args.ica + 2 * args.img - args.cl - args.lac
    HCO3 = hco3(args.ph, args.pco2)
    alb_charge = albumin_charge(args.alb, args.ph)
    pi_charge = phosphate_charge(args.phos, args.ph)
    SIDe = HCO3 + alb_charge + pi_charge
    SIG = SIDa - SIDe
    AG = args.na + args.k - args.cl - HCO3

    print(json.dumps({
        'SIDa': round(SIDa, 4),
        'SIDe': round(SIDe, 4),
        'SIG': round(SIG, 4),
        'AG': round(AG, 4),
        'HCO3': round(HCO3, 4),
        'Alb_charge_mEq_L': round(alb_charge, 4),
        'Pi_charge_mEq_L': round(pi_charge, 4)
    }))


def cmd_albumin_charge(args):
    charge = albumin_charge(args.alb, args.ph)
    net_per_mol = albumin_net_charge_per_mol(args.ph)
    print(json.dumps({
        'charge_mEq_L': round(charge, 4),
        'charge_Eq_per_mol': round(net_per_mol, 4)
    }))


def cmd_phosphate_charge(args):
    charge = phosphate_charge(args.phos, args.ph)
    print(json.dumps({
        'charge_mEq_L': round(charge, 4)
    }))


def main():
    parser = argparse.ArgumentParser(description='Figge-Fencl v3.0 acid-base model CLI')
    sub = parser.add_subparsers(dest='command')

    p_ph = sub.add_parser('predict-ph')
    p_ph.add_argument('--sid', type=float, required=True)
    p_ph.add_argument('--pco2', type=float, required=True)
    p_ph.add_argument('--pi', type=float, required=True)
    p_ph.add_argument('--alb', type=float, required=True)

    p_val = sub.add_parser('validate')
    p_val.add_argument('--data', type=str, required=True)

    p_ana = sub.add_parser('analyze')
    p_ana.add_argument('--na', type=float, required=True)
    p_ana.add_argument('--k', type=float, required=True)
    p_ana.add_argument('--ica', type=float, required=True)
    p_ana.add_argument('--img', type=float, required=True)
    p_ana.add_argument('--cl', type=float, required=True)
    p_ana.add_argument('--lac', type=float, required=True)
    p_ana.add_argument('--alb', type=float, required=True)
    p_ana.add_argument('--phos', type=float, required=True)
    p_ana.add_argument('--ph', type=float, required=True)
    p_ana.add_argument('--pco2', type=float, required=True)

    p_alb = sub.add_parser('albumin-charge')
    p_alb.add_argument('--alb', type=float, required=True)
    p_alb.add_argument('--ph', type=float, required=True)

    p_phos = sub.add_parser('phosphate-charge')
    p_phos.add_argument('--phos', type=float, required=True)
    p_phos.add_argument('--ph', type=float, required=True)

    args = parser.parse_args()

    if args.command == 'predict-ph':
        cmd_predict_ph(args)
    elif args.command == 'validate':
        cmd_validate(args)
    elif args.command == 'analyze':
        cmd_analyze(args)
    elif args.command == 'albumin-charge':
        cmd_albumin_charge(args)
    elif args.command == 'phosphate-charge':
        cmd_phosphate_charge(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
