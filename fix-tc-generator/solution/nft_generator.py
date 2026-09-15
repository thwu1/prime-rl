#!/usr/bin/env python3
"""
Generate nftables DSCP classification rules for tc class assignment.

Reads the multi-interface HTB topology and produces an nft ruleset
that classifies packets by DSCP value into the corresponding tc class
using meta priority set on the netdev hook.
"""
import yaml


# Standard DSCP value to nftables keyword mapping
DSCP_NFT_NAMES = {
    0: 'cs0', 8: 'cs1', 10: 'af11', 12: 'af12', 14: 'af13',
    16: 'cs2', 18: 'af21', 20: 'af22', 22: 'af23', 24: 'cs3',
    26: 'af31', 28: 'af32', 30: 'af33', 32: 'cs4', 34: 'af41',
    36: 'af42', 38: 'af43', 40: 'cs5', 46: 'ef', 48: 'cs6',
}


def dscp_nft_name(dscp_val):
    """Return nft-compatible DSCP name or numeric value."""
    return DSCP_NFT_NAMES.get(dscp_val, str(dscp_val))


def main():
    with open('/app/topology.yaml') as f:
        topology = yaml.safe_load(f)

    lines = []
    lines.append('#!/usr/sbin/nft -f')
    lines.append('# nftables DSCP-to-tc-class classification rules')
    lines.append('# Equivalent to tc u32 DSCP filters but using nftables netdev hook')
    lines.append('')
    lines.append('table netdev tc_classify {')

    for iface_name, iface in topology['interfaces'].items():
        chain_name = f"classify_{iface_name}"
        lines.append(f'    chain {chain_name} {{')
        lines.append(
            f'        type filter hook egress device "{iface_name}" '
            f'priority 0; policy accept;'
        )

        for parent_cls in iface['classes']:
            if 'children' in parent_cls:
                for child in parent_cls['children']:
                    if 'dscp' in child:
                        dscp = child['dscp']
                        dscp_name = dscp_nft_name(dscp)
                        classid = f"1:{child['minor']}"
                        lines.append(
                            f'        ip dscp {dscp_name} '
                            f'meta priority set {classid}'
                        )

        lines.append('    }')
        lines.append('')

    lines.append('}')
    lines.append('')

    with open('/app/nft_classify.nft', 'w') as f:
        f.write('\n'.join(lines))

    print("Generated /app/nft_classify.nft")


if __name__ == '__main__':
    main()
