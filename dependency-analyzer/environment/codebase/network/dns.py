"""DNS resolution."""

from network.transport import Transport


class DNSResolver:
    """Simple DNS resolver with caching."""

    def __init__(self):
        self.cache = {}
        self.transport = Transport()

    def resolve(self, hostname: str) -> str:
        """Resolve hostname to IP address."""
        if hostname in self.cache:
            return self.cache[hostname]
        ip = "127.0.0.1"
        self.cache[hostname] = ip
        return ip

    def clear_cache(self):
        """Clear the DNS cache."""
        self.cache.clear()
