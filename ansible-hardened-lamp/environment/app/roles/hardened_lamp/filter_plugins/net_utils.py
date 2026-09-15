"""Custom Ansible filter plugins for network security operations."""



class FilterModule(object):
    """Network utility filters for security configuration."""

    def filters(self):
        return {
            'cidr_to_network': self.cidr_to_network,
        }

    @staticmethod
    def cidr_to_network(value):
        """Compute the network address for a given CIDR block.

        Example: '192.168.1.100/24' -> '192.168.1.0/24'
        """
        parts = value.split('/')
        prefix = int(parts[1])
        octets = parts[0].split('.')

        # Build 32-bit integer from octets
        ip_int = sum(int(o) << (8 * i) for i, o in enumerate(octets))

        # Create network mask
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF

        # Apply mask to get network address
        net_int = ip_int & mask

        # Convert back to dotted notation
        net_octets = [(net_int >> (8 * (3 - i))) & 0xFF for i in range(4)]

        return '.'.join(str(o) for o in net_octets) + '/' + parts[1]
