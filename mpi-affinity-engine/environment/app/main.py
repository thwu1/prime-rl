#!/usr/bin/env python3
"""MPI Job Configuration Validator and Generator.

Validates and generates Intel MPI process pinning configurations
for hybrid MPI+OpenMP applications on multi-socket NUMA systems.
"""

import argparse
import json
import sys
from affinity_engine.topology import Topology
from affinity_engine.placement import place_ranks
from affinity_engine.affinity import generate_rank_masks
from affinity_engine.env_generator import generate_env_script
from affinity_engine.diagnostics import generate_report


def main():
    parser = argparse.ArgumentParser(
        description='MPI Job Configuration Validator and Generator'
    )
    parser.add_argument('topology', help='Path to topology JSON file')
    parser.add_argument('--ranks', '-n', type=int, required=True,
                        help='Number of MPI ranks')
    parser.add_argument('--threads', '-t', type=int, default=1,
                        help='OpenMP threads per rank')
    parser.add_argument('--policy', '-p', choices=['compact', 'scatter'],
                        default='compact', help='Placement policy')
    parser.add_argument('--domain', '-d',
                        choices=['auto', 'socket', 'numa', 'core', 'omp'],
                        default='auto', help='I_MPI_PIN_DOMAIN mode')
    parser.add_argument('--no-ht', action='store_true',
                        help='Exclude HyperThread siblings from affinity masks')
    parser.add_argument('--env-script', '-e', type=str,
                        help='Write environment script to file')
    parser.add_argument('--report', '-r', action='store_true',
                        help='Generate diagnostic report')
    parser.add_argument('--masks', '-m', action='store_true',
                        help='Output affinity masks')
    parser.add_argument('--json-output', '-j', type=str,
                        help='Write JSON output to file')

    args = parser.parse_args()

    topology = Topology.from_json(args.topology)

    cores_per_rank = args.threads if args.threads > 1 else 1

    placement = place_ranks(topology, args.ranks, cores_per_rank, args.policy)

    include_ht = not args.no_ht
    masks = generate_rank_masks(placement, include_ht=include_ht)

    if args.report:
        report = generate_report(topology, args.ranks, args.threads,
                                 placement, include_ht)
        print(report)

    if args.masks:
        print("Affinity Masks:")
        for rank, info in masks.items():
            print(f"  Rank {rank}: {info['mask_hex']} -> CPUs {info['cpu_list']}")

    if args.env_script:
        script = generate_env_script(topology, args.ranks, args.threads,
                                     placement, args.domain, args.policy)
        with open(args.env_script, 'w') as f:
            f.write(script)
        print(f"Environment script written to {args.env_script}")

    if args.json_output:
        output = {
            'topology': topology.name,
            'num_ranks': args.ranks,
            'threads_per_rank': args.threads,
            'policy': args.policy,
            'placement': {},
            'masks': {}
        }
        for rank in range(args.ranks):
            cores = placement.get_rank_cores(rank)
            output['placement'][str(rank)] = {
                'physical_cores': [c.physical_id for c in cores],
                'logical_cpus': placement.get_rank_logical_cpus(rank),
                'numa_nodes': sorted(set(c.numa_node_id for c in cores)),
                'sockets': sorted(set(c.socket_id for c in cores))
            }
            output['masks'][str(rank)] = {
                'mask_hex': masks[rank]['mask_hex'],
                'cpu_list': masks[rank]['cpu_list']
            }

        with open(args.json_output, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"JSON output written to {args.json_output}")

    if not any([args.report, args.masks, args.env_script, args.json_output]):
        report = generate_report(topology, args.ranks, args.threads,
                                 placement, include_ht)
        print(report)


if __name__ == '__main__':
    main()
