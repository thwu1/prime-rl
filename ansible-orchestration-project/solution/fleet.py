from ansible.plugins.inventory import BaseInventoryPlugin
import json

DOCUMENTATION = r'''
    name: fleet
    plugin_type: inventory
    short_description: Fleet JSON inventory source
    description:
        - Reads fleet inventory data from a JSON file.
        - Groups hosts by datacenter and role.
        - Creates compound groups in the format datacenter_role.
        - Computes capacity_utilization and usable_hosts per host.
        - Excludes hosts where status is decommissioned.
    options:
        plugin:
            description: Name of the plugin
            required: true
            choices: ['fleet']
        fleet_file:
            description: Path to the fleet inventory JSON file
            required: true
            type: string
'''


class InventoryModule(BaseInventoryPlugin):
    NAME = 'fleet'

    def verify_file(self, path):
        valid = False
        if super().verify_file(path):
            if path.endswith(('.yml', '.yaml', '.json')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        self._read_config_data(path)

        fleet_file = self.get_option('fleet_file')

        with open(fleet_file, 'r') as f:
            fleet_data = json.load(f)

        for host in fleet_data.get('hosts', []):
            if host.get('status') == 'decommissioned':
                continue

            hostname = host['hostname']
            self.inventory.add_host(hostname)

            self.inventory.set_variable(hostname, 'ansible_host', host.get('ip', '127.0.0.1'))
            self.inventory.set_variable(hostname, 'ansible_connection', 'local')
            self.inventory.set_variable(hostname, 'fqdn', host.get('fqdn', hostname))
            self.inventory.set_variable(hostname, 'risk_score', host.get('risk_score', 0))
            self.inventory.set_variable(hostname, 'compliance_tags', host.get('compliance_tags', []))
            self.inventory.set_variable(hostname, 'network_cidr', host.get('network', {}).get('cidr', ''))

            # Compute capacity utilization
            res = host.get('resources', {})
            cpu_cores = res.get('cpu_cores', 1)
            alloc_cpu = res.get('allocated_cpu', 0)
            mem_total = res.get('memory_bytes', 1)
            alloc_mem = res.get('allocated_memory_bytes', 0)
            disk_total = res.get('disk_bytes', 1)
            alloc_disk = res.get('allocated_disk_bytes', 0)

            cpu_pct = alloc_cpu / cpu_cores
            mem_pct = alloc_mem / mem_total
            disk_pct = alloc_disk / disk_total
            capacity = cpu_pct * 40 + mem_pct * 35 + disk_pct * 25
            self.inventory.set_variable(hostname, 'capacity_utilization', round(capacity, 2))

            # Compute usable network hosts from CIDR
            cidr = host.get('network', {}).get('cidr', '')
            if '/' in cidr:
                prefix = int(cidr.split('/')[1])
                usable = (2 ** (32 - prefix)) - 2
            else:
                usable = 0
            self.inventory.set_variable(hostname, 'usable_hosts', usable)

            # Group by datacenter
            dc = host.get('datacenter', 'unknown')
            self.inventory.add_group(dc)
            self.inventory.add_host(hostname, group=dc)

            # Group by role
            role = host.get('role', 'unknown')
            self.inventory.add_group(role)
            self.inventory.add_host(hostname, group=role)

            # Compound group: datacenter_role
            compound = f"{dc}_{role}"
            self.inventory.add_group(compound)
            self.inventory.add_host(hostname, group=compound)
