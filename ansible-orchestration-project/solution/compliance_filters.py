import hashlib
import re


class FilterModule(object):
    """Custom Ansible filter plugins for fleet compliance automation."""

    def filters(self):
        return {
            'risk_grade': self.risk_grade,
            'capacity_status': self.capacity_status,
            'cidr_host_count': self.cidr_host_count,
            'mask_credential': self.mask_credential,
            'sha256_digest': self.sha256_digest,
        }

    def risk_grade(self, score):
        """Map numeric risk score to letter grade."""
        score = float(score)
        if score <= 20:
            return 'A'
        elif score <= 40:
            return 'B'
        elif score <= 60:
            return 'C'
        elif score <= 80:
            return 'D'
        else:
            return 'F'

    def capacity_status(self, utilization):
        """Map capacity utilization to status string."""
        utilization = float(utilization)
        if utilization < 60:
            return 'green'
        elif utilization < 80:
            return 'yellow'
        else:
            return 'red'

    def cidr_host_count(self, cidr):
        """Compute usable host count from CIDR notation."""
        prefix = int(str(cidr).split('/')[-1])
        return (2 ** (32 - prefix)) - 2

    def mask_credential(self, value):
        """Mask credential: show first 3 + last 2 chars, asterisks in between."""
        value = str(value)
        if len(value) <= 5:
            return '*' * len(value)
        return value[:3] + '*' * (len(value) - 5) + value[-2:]

    def sha256_digest(self, value):
        """Return hex SHA256 digest of input string."""
        return hashlib.sha256(str(value).encode()).hexdigest()
