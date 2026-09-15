"""
IPAM data models for VRF-aware prefix hierarchy management.
Models the core entities of IP address management: VRFs, prefixes,
IP addresses, and IP ranges, inspired by NetBox's IPAM module.
"""
import netaddr


class VRF:
    """Virtual Routing and Forwarding instance."""

    def __init__(self, name, rd=None, enforce_unique=True):
        self.name = name
        self.rd = rd
        self.enforce_unique = enforce_unique
        self.import_targets = set()
        self.export_targets = set()

    def __repr__(self):
        if self.rd:
            return f"VRF({self.name}, {self.rd})"
        return f"VRF({self.name})"

    def __eq__(self, other):
        if other is None:
            return False
        if not isinstance(other, VRF):
            return False
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)


class Prefix:
    """An IPv4 or IPv6 network prefix with VRF association."""
    STATUS_ACTIVE = 'active'
    STATUS_CONTAINER = 'container'
    STATUS_RESERVED = 'reserved'

    def __init__(self, prefix, vrf=None, status='active', is_pool=False,
                 mark_utilized=False, site=None):
        if isinstance(prefix, str):
            self.prefix = netaddr.IPNetwork(prefix)
        else:
            self.prefix = prefix
        self.vrf = vrf
        self.status = status
        self.is_pool = is_pool
        self.mark_utilized = mark_utilized
        self.site = site
        self._depth = 0
        self._children = 0

    def __repr__(self):
        vrf_str = f", vrf={self.vrf.name}" if self.vrf else ""
        return f"Prefix({self.prefix}{vrf_str})"

    @property
    def family(self):
        return self.prefix.version


class IPAddress:
    """An individual IPv4 or IPv6 address with mask."""

    def __init__(self, address, vrf=None):
        if isinstance(address, str):
            self.address = netaddr.IPNetwork(address)
        else:
            self.address = address
        self.vrf = vrf

    def __repr__(self):
        return f"IP({self.address})"

    @property
    def family(self):
        return self.address.version


class IPRange:
    """A contiguous range of IP addresses."""

    def __init__(self, start_address, end_address, vrf=None, mark_utilized=False):
        self.start_address = netaddr.IPNetwork(start_address)
        self.end_address = netaddr.IPNetwork(end_address)
        self.vrf = vrf
        self.mark_utilized = mark_utilized

    @property
    def range(self):
        return netaddr.IPRange(self.start_address.ip, self.end_address.ip)

    @property
    def size(self):
        return int(self.end_address.ip - self.start_address.ip) + 1
