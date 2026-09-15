from ansible.plugins.inventory import BaseInventoryPlugin
import json

DOCUMENTATION = r'''
    name: cmdb
    plugin_type: inventory
    short_description: CMDB JSON inventory source
    description:
        - Reads infrastructure node data from a CMDB JSON file.
        - Groups hosts by environment, role, and tier.
        - Creates compound groups in the format environment_role.
        - Excludes nodes where managed is false.
    options:
        plugin:
            description: Name of the plugin
            required: true
            choices: ['cmdb']
        cmdb_file:
            description: Path to the CMDB JSON file
            required: true
            type: string
'''


class InventoryModule(BaseInventoryPlugin):
    NAME = 'cmdb'

    def verify_file(self, path):
        valid = False
        if super().verify_file(path):
            if path.endswith(('.yml', '.yaml', '.json')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        self._read_config_data(path)

        cmdb_file = self.get_option('cmdb_file')

        with open(cmdb_file, 'r') as f:
            cmdb_data = json.load(f)

        for node in cmdb_data.get('nodes', []):
            if not node.get('managed', True):
                continue

            hostname = node['hostname']
            self.inventory.add_host(hostname)

            # Set host variables
            self.inventory.set_variable(hostname, 'ansible_host', node.get('ip', '127.0.0.1'))
            self.inventory.set_variable(hostname, 'ansible_connection', 'local')
            self.inventory.set_variable(hostname, 'fqdn', node.get('fqdn', hostname))
            self.inventory.set_variable(hostname, 'tier', node.get('tier', ''))
            self.inventory.set_variable(hostname, 'node_tags', node.get('tags', []))
            self.inventory.set_variable(hostname, 'os_family', node.get('os_family', ''))

            # Group by environment
            env = node.get('environment', 'unknown')
            self.inventory.add_group(env)
            self.inventory.add_host(hostname, group=env)

            # Group by role
            role = node.get('role', 'unknown')
            self.inventory.add_group(role)
            self.inventory.add_host(hostname, group=role)

            # Group by tier
            tier = node.get('tier', 'unknown')
            self.inventory.add_group(tier)
            self.inventory.add_host(hostname, group=tier)

            # Compound group: environment_role
            compound = f"{env}_{role}"
            self.inventory.add_group(compound)
            self.inventory.add_host(hostname, group=compound)
