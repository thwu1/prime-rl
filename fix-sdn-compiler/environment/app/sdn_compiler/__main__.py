#!/usr/bin/env python3
"""SDN Configuration Compiler - CLI entry point.

Generates Linux networking commands and FRR configuration for
Proxmox-style SDN zones with EVPN/VXLAN overlay networking.

Usage:
    python3 -m sdn_compiler --cluster configs/cluster.yaml \\
                            --sdn configs/sdn.yaml \\
                            --node pve01 \\
                            --output-dir /tmp/sdn_output
"""

import argparse
import os
import sys

from .parser import parse_cluster_config, parse_sdn_config
from .validator import validate_config
from .generator import generate_network_config
from .frr import generate_frr_config


def main():
    parser = argparse.ArgumentParser(
        description='SDN Configuration Compiler'
    )
    parser.add_argument('--cluster', required=True,
                        help='Path to cluster config YAML')
    parser.add_argument('--sdn', required=True,
                        help='Path to SDN config YAML')
    parser.add_argument('--node', required=True,
                        help='Node name to generate config for')
    parser.add_argument('--output-dir', default='.',
                        help='Output directory')
    parser.add_argument('--validate-only', action='store_true',
                        help='Only validate, do not generate')

    args = parser.parse_args()

    # Parse configs
    cluster_config = parse_cluster_config(args.cluster)
    sdn_config = parse_sdn_config(args.sdn)

    # Validate
    is_valid, errors = validate_config(sdn_config, cluster_config)
    if errors:
        print("Validation errors:")
        for err in errors:
            print(f"  - {err}")
        if not is_valid:
            sys.exit(1)
    else:
        print("Configuration valid.")

    if args.validate_only:
        sys.exit(0)

    # Check node exists
    if args.node not in cluster_config.nodes:
        print(f"Error: node '{args.node}' not in cluster config")
        sys.exit(1)

    # Generate configs
    os.makedirs(args.output_dir, exist_ok=True)

    network_config = generate_network_config(sdn_config, cluster_config,
                                             args.node)
    frr_config = generate_frr_config(sdn_config, cluster_config, args.node)

    net_path = os.path.join(args.output_dir, 'network.sh')
    frr_path = os.path.join(args.output_dir, 'frr.conf')

    with open(net_path, 'w') as f:
        f.write(network_config)

    with open(frr_path, 'w') as f:
        f.write(frr_config)

    print(f"Network config written to {net_path}")
    print(f"FRR config written to {frr_path}")


if __name__ == '__main__':
    main()
