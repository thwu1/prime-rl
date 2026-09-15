#!/usr/bin/python

from ansible.module_utils.basic import AnsibleModule
import json

DOCUMENTATION = r"""
module: fleet_validate
short_description: Validate fleet host compliance
description:
    - Checks a host's capacity utilization and risk score against thresholds
options:
    fleet_file:
        description: Path to the fleet inventory JSON file
        type: str
        required: true
    hostname:
        description: Name of the host to validate
        type: str
        required: true
    risk_threshold:
        description: Maximum acceptable risk score
        type: int
        required: true
    capacity_threshold:
        description: Maximum acceptable capacity utilization percentage
        type: float
        required: true
    capacity_weights:
        description: Weight dictionary with keys cpu, memory, disk
        type: dict
        required: true
"""


def main():
    module = AnsibleModule(
        argument_spec=dict(
            fleet_file=dict(type='str', required=True),
            hostname=dict(type='str', required=True),
            risk_threshold=dict(type='int', required=True),
            capacity_threshold=dict(type='float', required=True),
            capacity_weights=dict(type='dict', required=True),
        ),
        supports_check_mode=True
    )

    fleet_file = module.params['fleet_file']
    hostname = module.params['hostname']
    risk_threshold = module.params['risk_threshold']
    capacity_threshold = module.params['capacity_threshold']
    weights = module.params['capacity_weights']

    try:
        with open(fleet_file) as f:
            fleet_data = json.load(f)
    except Exception as e:
        module.fail_json(msg="Failed to read fleet file: {}".format(e))

    host = None
    for h in fleet_data.get('hosts', []):
        if h['hostname'] == hostname and h.get('status') != 'decommissioned':
            host = h
            break

    if host is None:
        module.fail_json(msg="Host '{}' not found or decommissioned".format(hostname))

    violations = []
    res = host['resources']
    cpu_pct = res['allocated_cpu'] / res['cpu_cores']
    mem_pct = res['allocated_memory_bytes'] / res['memory_bytes']
    disk_pct = res['allocated_disk_bytes'] / res['disk_bytes']

    w_cpu = float(weights.get('cpu', 0))
    w_mem = float(weights.get('memory', 0))
    w_disk = float(weights.get('disk', 0))
    capacity = cpu_pct * w_cpu + mem_pct * w_mem + disk_pct * w_disk

    if capacity >= capacity_threshold:
        violations.append("capacity {:.2f} >= {}".format(capacity, capacity_threshold))

    if host['risk_score'] > risk_threshold:
        violations.append("risk_score {} > {}".format(host['risk_score'], risk_threshold))

    compliant = len(violations) == 0

    module.exit_json(
        changed=False,
        compliant=compliant,
        capacity_utilization=round(capacity, 2),
        violations=violations,
        msg="Host {}: {}".format(hostname, 'COMPLIANT' if compliant else 'NON-COMPLIANT')
    )


if __name__ == '__main__':
    main()
