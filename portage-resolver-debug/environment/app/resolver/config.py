"""
Portage configuration parser.

Reads make.conf for global USE flags and package.use/* for per-package
overrides.  Computes effective USE flags for each package in the system.
"""

import os
import re


class PortageConfig:
    """Parse and compute effective USE flags from Portage configuration."""

    def __init__(self, portage_dir):
        self.portage_dir = portage_dir
        self.global_use = set()
        self.package_use = {}   # {cp: set(flags)}
        self._parse()

    def _parse(self):
        make_conf = os.path.join(self.portage_dir, 'make.conf')
        if os.path.isfile(make_conf):
            self._parse_make_conf(make_conf)
        pkg_use_dir = os.path.join(self.portage_dir, 'package.use')
        if os.path.isdir(pkg_use_dir):
            for fname in sorted(os.listdir(pkg_use_dir)):
                fpath = os.path.join(pkg_use_dir, fname)
                if os.path.isfile(fpath):
                    self._parse_package_use(fpath)

    def _parse_make_conf(self, path):
        """Parse make.conf to extract global USE flags."""
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                m = re.match(r'USE\s*=\s*["\'](.+?)["\']', line)
                if m:
                    for tok in m.group(1).split():
                        # Normalize flag name — strip any prefix sigils
                        self.global_use.add(tok.lstrip('-'))

    def _parse_package_use(self, path):
        """Parse a package.use file for per-package USE overrides."""
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                if '#' in line:
                    line = line[:line.index('#')].strip()
                parts = line.split()
                if len(parts) < 2:
                    continue
                cp = parts[0]
                flags = set()
                for tok in parts[1:]:
                    if tok.startswith('-'):
                        flags.discard(tok[1:])
                    else:
                        flags.add(tok)
                self.package_use[cp] = flags

    def get_effective_use(self, cp):
        """Compute effective USE flags for a package.

        Effective flags = global USE merged with per-package overrides.
        """
        result = set(self.global_use)
        if cp in self.package_use:
            result |= self.package_use[cp]
        return result
