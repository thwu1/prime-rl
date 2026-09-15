#!/usr/bin/env python3
"""Parse Nordic nRF Connect SDK Partition Manager pm_static.yml.

Outputs shell variable assignments for mcuboot_primary and mcuboot_secondary
partition addresses and sizes, suitable for eval in bash.
"""
import sys
import yaml

PM_CONFIG = '/app/build_config/pm_static.yml'


def main():
    with open(PM_CONFIG) as f:
        pm = yaml.safe_load(f)

    if 'mcuboot_primary' not in pm:
        print("ERROR: mcuboot_primary partition not found in pm_static.yml",
              file=sys.stderr)
        sys.exit(1)
    if 'mcuboot_secondary' not in pm:
        print("ERROR: mcuboot_secondary partition not found in pm_static.yml",
              file=sys.stderr)
        sys.exit(1)

    primary = pm['mcuboot_primary']
    secondary = pm['mcuboot_secondary']

    print(f"PRIMARY_OFFSET={primary['address']}")
    print(f"PRIMARY_SIZE={primary['size']}")
    print(f"SECONDARY_OFFSET={secondary['address']}")
    print(f"SECONDARY_SIZE={secondary['size']}")


if __name__ == '__main__':
    main()
