"""
Core IPAM engine for VRF-aware prefix hierarchy management,
allocation, and utilization calculation.

Inspired by NetBox's IPAM module (netbox-community/netbox).
Implements prefix containment, available prefix/IP discovery,
utilization tracking, and hierarchy depth/children caching.
"""
import netaddr

from .models import Prefix, IPAddress


class IPAMEngine:
    """Engine for managing VRF-aware IP address hierarchies."""

    def __init__(self):
        self.prefixes = []
        self.ip_addresses = []
        self.ip_ranges = []
        self.aggregates = []
        self.vrfs = []

    def add_prefix(self, prefix):
        """Add a prefix to the engine."""
        self.prefixes.append(prefix)
        return prefix

    def add_ip(self, ip):
        """Add an IP address to the engine."""
        self.ip_addresses.append(ip)
        return ip

    # ---- Prefix hierarchy ----

    def get_child_prefixes(self, parent):
        """
        Return all prefixes contained within the parent prefix,
        filtered to the same VRF.
        """
        children = []
        for p in self.prefixes:
            if p.prefix in parent.prefix:
                if p.vrf == parent.vrf:
                    children.append(p)
        return children

    def get_available_prefixes(self, parent):
        """
        Return all available (unallocated) prefix space within parent
        as an IPSet.
        """
        children = self.get_child_prefixes(parent)
        child_set = netaddr.IPSet([c.prefix for c in children])
        return netaddr.IPSet(parent.prefix) - child_set

    def find_first_available_prefix(self, parent, prefix_length):
        """
        Find the first available prefix of the given length within parent.
        Returns an IPNetwork or None.
        """
        available = self.get_available_prefixes(parent)
        if not available:
            return None
        for cidr in available.iter_cidrs():
            if cidr.prefixlen <= prefix_length:
                subnets = list(cidr.subnet(prefix_length))
                if subnets:
                    return subnets[0]
        return None

    # ---- IP address management ----

    def get_child_ips(self, prefix):
        """
        Return all IP addresses within the given prefix and its VRF.
        """
        children = []
        for ip in self.ip_addresses:
            if ip.address.ip in prefix.prefix and ip.vrf == prefix.vrf:
                children.append(ip)
        return children

    def get_available_ips(self, prefix):
        """
        Return all available IPs within this prefix as an IPSet.
        Handles pool vs non-pool and IPv4 vs IPv6 semantics.
        """
        prefix_set = netaddr.IPSet(prefix.prefix)

        # Subtract assigned IPs
        child_ips = netaddr.IPSet([
            ip.address.ip for ip in self.get_child_ips(prefix)
        ])
        # Subtract utilized ranges
        child_ranges = netaddr.IPSet()
        for r in self.ip_ranges:
            if r.mark_utilized and r.vrf == prefix.vrf:
                if r.start_address.ip in prefix.prefix:
                    child_ranges.add(r.range)

        available = prefix_set - child_ips - child_ranges

        # Pool, /31-/32 (IPv4) or /127-/128 (IPv6) are fully usable
        if (prefix.is_pool or
                (prefix.family == 4 and prefix.prefix.prefixlen >= 31) or
                (prefix.family == 6 and prefix.prefix.prefixlen >= 127)):
            return available

        # Subtract reserved addresses
        if prefix.family == 4:
            # IPv4: subtract network and broadcast addresses
            available -= netaddr.IPSet([
                netaddr.IPAddress(prefix.prefix.first),
                netaddr.IPAddress(prefix.prefix.last),
            ])
        else:
            # IPv6: only subtract subnet-router anycast (first) per RFC 4291
            available -= netaddr.IPSet([
                netaddr.IPAddress(prefix.prefix.first),
            ])

        return available

    def allocate_next_ip(self, prefix):
        """Allocate the next available IP address in the prefix."""
        available = self.get_available_ips(prefix)
        if not available:
            return None
        ip_addr = next(available.__iter__())
        ip = IPAddress(
            address=f"{ip_addr}/{prefix.prefix.prefixlen}",
            vrf=prefix.vrf
        )
        self.add_ip(ip)
        return ip

    # ---- Utilization ----

    def get_prefix_utilization(self, prefix):
        """
        Calculate utilization percentage for a prefix.
        - Container prefixes: utilization based on child prefix address space
        - Active prefixes: utilization based on child IP addresses
        - mark_utilized: always returns 100%
        """
        if prefix.mark_utilized:
            return 100.0

        if prefix.status == Prefix.STATUS_CONTAINER:
            children = self.get_child_prefixes(prefix)
            child_set = netaddr.IPSet([c.prefix for c in children])
            utilization = float(child_set.size) / prefix.prefix.size * 100
            return min(utilization, 100.0)

        else:
            # Active prefix: count child IPs and utilized ranges
            child_ips = netaddr.IPSet()
            for r in self.ip_ranges:
                if r.mark_utilized and r.vrf == prefix.vrf:
                    if r.start_address.ip in prefix.prefix:
                        child_ips.add(r.range)
            for ip in self.get_child_ips(prefix):
                child_ips.add(ip.address.ip)

            prefix_size = prefix.prefix.size
            if prefix.family == 4 and prefix.prefix.prefixlen < 31 and not prefix.is_pool:
                prefix_size -= 2
            utilization = float(child_ips.size) / prefix_size * 100
            return min(utilization, 100.0)

    # ---- Hierarchy rebuild ----

    def rebuild_hierarchy(self):
        """
        Rebuild _depth and _children counts for all prefixes.
        Depth = number of ancestor prefixes in the same VRF.
        Children = number of descendant prefixes in the same VRF.
        """
        for p in self.prefixes:
            # Calculate depth: count ancestor prefixes
            depth = 0
            for other in self.prefixes:
                if other is p:
                    continue
                if p.prefix in other.prefix and other.prefix.prefixlen < p.prefix.prefixlen:
                    if other.vrf == p.vrf:
                        depth += 1
            p._depth = depth

            # Calculate children count
            children = 0
            for other in self.prefixes:
                if other is p:
                    continue
                if other.prefix in p.prefix and other.prefix.prefixlen > p.prefix.prefixlen:
                    if other.vrf == p.vrf:
                        children += 1
            p._children = children
