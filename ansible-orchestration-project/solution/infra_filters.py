import re


class FilterModule(object):
    """Custom Ansible filter plugins for infrastructure automation."""

    def filters(self):
        return {
            'normalize_hostname': self.normalize_hostname,
            'mask_secret': self.mask_secret,
            'bytes_to_human': self.bytes_to_human,
        }

    def normalize_hostname(self, value):
        """Normalize a string into a valid hostname."""
        value = str(value).lower()
        value = re.sub(r'[^a-z0-9\-]', '-', value)
        value = re.sub(r'-+', '-', value)
        value = value.strip('-')
        return value

    def mask_secret(self, value):
        """Mask the middle of a secret string with asterisks."""
        value = str(value)
        if len(value) <= 4:
            return '*' * len(value)
        return value[:2] + '*' * (len(value) - 4) + value[-2:]

    def bytes_to_human(self, value):
        """Convert bytes to human-readable format."""
        value = int(value)
        if value == 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        v = float(value)
        while v >= 1024 and i < len(units) - 1:
            v /= 1024
            i += 1
        return f"{v:.2f} {units[i]}"
