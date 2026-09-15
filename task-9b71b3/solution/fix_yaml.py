#!/usr/bin/env python3
"""Remove the scibase version lock from spack.yaml packages section."""

import yaml

SPACK_YAML = "/app/env/spack.yaml"

with open(SPACK_YAML) as f:
    data = yaml.safe_load(f)

spack_section = data.get("spack", {})
packages = spack_section.get("packages", {})

if "scibase" in packages:
    del packages["scibase"]

if not packages and "packages" in spack_section:
    del spack_section["packages"]

with open(SPACK_YAML, "w") as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
