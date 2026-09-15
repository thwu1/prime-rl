#!/usr/bin/env python3
"""
Preprocess site investigation data into analysis-ready JSON scenarios.

Reads:
  - config.ini: Site parameters, foundation geometry, consolidation settings
  - soil_profile.csv (optional): Soil layer properties

Produces:
  - scenario.json: Input for geosettle.py
"""
import argparse
import configparser
import csv
import json
import os


def parse_soil_csv(csv_path):
    """Parse soil profile CSV into list of layer dictionaries."""
    layers = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            layers.append({
                "depth_from": float(row["depth_from"]),
                "depth_to": float(row["depth_to"]),
                "total_unit_weight": float(row["total_unit_weight"]),
                "Cc": float(row["Cc"]),
                "Cr": float(row["Cr"]),
                "OCR": float(row["OCR"])
            })
    return layers


def parse_config(config_path):
    """Parse INI config file into scenario dictionary components."""
    config = configparser.ConfigParser()
    config.read(config_path)

    scenario = {}

    if config.has_section('site'):
        scenario["water_table_depth"] = config.getfloat('site', 'water_table_depth', fallback=0.0)
        scenario["specific_gravity"] = config.getfloat('site', 'specific_gravity', fallback=2.65)
        scenario["unit_weight_water"] = config.getfloat('site', 'unit_weight_water', fallback=10.0)
        scenario["grid_spacing"] = config.getfloat('site', 'grid_spacing', fallback=0.5)

    if config.has_section('foundation'):
        foundation = {
            "shape": config.get('foundation', 'shape'),
            "width": config.getfloat('foundation', 'width'),
            "applied_stress": config.getfloat('foundation', 'applied_stress')
        }
        if foundation["shape"] == "rectangular":
            foundation["length"] = config.getfloat('foundation', 'length')
        scenario["foundation"] = foundation

    if config.has_section('consolidation'):
        cons = {
            "height": config.getfloat('consolidation', 'height'),
            "total_time": config.getfloat('consolidation', 'total_time'),
            "no_nodes": config.getint('consolidation', 'no_nodes'),
            "cv": config.getfloat('consolidation', 'cv'),
            "top_drainage": config.getboolean('consolidation', 'top_drainage'),
            "bottom_drainage": config.getboolean('consolidation', 'bottom_drainage'),
        }

        pp_str = config.get('consolidation', 'initial_excess_pore_pressure')
        if ',' in pp_str:
            cons["initial_excess_pore_pressure"] = [float(x.strip()) for x in pp_str.split(',')]
        else:
            cons["initial_excess_pore_pressure"] = float(pp_str)

        times_str = config.get('consolidation', 'output_times_seconds')
        cons["output_times_seconds"] = [float(x.strip()) for x in times_str.split(',')]

        scenario["consolidation"] = cons

    return scenario


def main():
    parser = argparse.ArgumentParser(description='Preprocess site data into JSON scenario')
    parser.add_argument('--config', required=True, help='Path to config.ini')
    parser.add_argument('--soil', help='Path to soil_profile.csv')
    parser.add_argument('--output', required=True, help='Output JSON path')
    args = parser.parse_args()

    scenario = parse_config(args.config)

    if args.soil and os.path.exists(args.soil):
        layers = parse_soil_csv(args.soil)
        scenario["soil_profile"] = {"layers": layers}

    with open(args.output, 'w') as f:
        json.dump(scenario, f, indent=2)


if __name__ == '__main__':
    main()
