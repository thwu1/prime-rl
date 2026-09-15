"""
Natural circulation analysis for pebble-bed HTGR decay heat removal.

Reads reactor configuration, runs the natural circulation solver for
each post-shutdown time point, and writes results to CSV.

Usage:
    python3 -m natcirc_sim [config_file] [output_file]
"""
import sys
import csv
import tomllib
from . import loop


def run_analysis(config_path='/app/reactor.toml',
                 output_path='/app/results.csv'):
    """Run the full decay heat removal analysis."""
    with open(config_path, 'rb') as f:
        config = tomllib.load(f)

    P = config['conditions']['pressure_Pa']
    T_in = config['conditions']['inlet_temperature_K']
    Q0 = config['conditions']['thermal_power_W']
    n_nodes = config['simulation']['n_axial_nodes']
    time_points = config['simulation']['time_points_hours']
    dc = config['decay_heat']['coefficient']
    de = config['decay_heat']['exponent']

    fieldnames = [
        'time_hours', 'decay_heat_MW', 'mass_flow_rate_kg_s',
        'outlet_temp_K', 'peak_surface_temp_K', 'peak_centerline_temp_K',
        'core_dp_Pa',
    ]

    rows = []
    for t_hr in time_points:
        t_sec = t_hr * 3600.0
        Q_decay = Q0 * dc * t_sec ** de

        result = loop.solve_steady_state(Q_decay, T_in, P, config, n_nodes)

        rows.append({
            'time_hours': f'{t_hr:.1f}',
            'decay_heat_MW': f'{Q_decay / 1e6:.6f}',
            'mass_flow_rate_kg_s': f'{result["mdot"]:.6f}',
            'outlet_temp_K': f'{result["T_out"]:.4f}',
            'peak_surface_temp_K': f'{result["peak_T_surf"]:.4f}',
            'peak_centerline_temp_K': f'{result["peak_T_center"]:.4f}',
            'core_dp_Pa': f'{result["core_dp"]:.4f}',
        })

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f'Analysis complete. Results written to {output_path}')


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else '/app/reactor.toml'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/results.csv'
    run_analysis(config_path, output_path)


if __name__ == '__main__':
    main()
