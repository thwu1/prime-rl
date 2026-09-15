#!/usr/bin/env python3
"""Generate synthetic dn42 registry with schema definitions, policy, and planted violations."""
import os

BASE = "/app/registry/data"

# --- Schema definitions (agent must parse these to discover validation rules) ---
SCHEMAS = {
    "MNTNER-SCHEMA": (
        "schema:             MNTNER-SCHEMA\n"
        "ref:                dn42.mntner\n"
        "key:                mntner      required  single    primary\n"
        "key:                descr       optional  multiple\n"
        "key:                admin-c     required  single    lookup=dn42.person\n"
        "key:                tech-c      required  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                auth        required  multiple\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "PERSON-SCHEMA": (
        "schema:             PERSON-SCHEMA\n"
        "ref:                dn42.person\n"
        "key:                person      required  single    primary\n"
        "key:                e-mail      optional  multiple\n"
        "key:                nic-hdl     required  single\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                contact     optional  multiple\n"
        "key:                pgp-fingerprint  optional  multiple\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "AUT-NUM-SCHEMA": (
        "schema:             AUT-NUM-SCHEMA\n"
        "ref:                dn42.aut-num\n"
        "key:                aut-num     required  single    primary\n"
        "key:                as-name     required  single\n"
        "key:                descr       optional  multiple\n"
        "key:                admin-c     required  single    lookup=dn42.person\n"
        "key:                tech-c      required  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "INETNUM-SCHEMA": (
        "schema:             INETNUM-SCHEMA\n"
        "ref:                dn42.inetnum\n"
        "key:                inetnum     required  single    primary\n"
        "key:                cidr        required  single\n"
        "key:                netname     required  single\n"
        "key:                descr       optional  multiple\n"
        "key:                country     optional  single\n"
        "key:                admin-c     required  single    lookup=dn42.person\n"
        "key:                tech-c      required  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                status      required  single    enum=ASSIGNED,ALLOCATED\n"
        "key:                policy      optional  single    enum=open,closed,ask,reserved\n"
        "key:                nserver     optional  multiple\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "INET6NUM-SCHEMA": (
        "schema:             INET6NUM-SCHEMA\n"
        "ref:                dn42.inet6num\n"
        "key:                inet6num    required  single    primary\n"
        "key:                cidr        required  single\n"
        "key:                netname     required  single\n"
        "key:                descr       optional  multiple\n"
        "key:                country     optional  single\n"
        "key:                admin-c     required  single    lookup=dn42.person\n"
        "key:                tech-c      required  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                status      required  single    enum=ASSIGNED,ALLOCATED\n"
        "key:                nserver     optional  multiple\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "ROUTE-SCHEMA": (
        "schema:             ROUTE-SCHEMA\n"
        "ref:                dn42.route\n"
        "key:                route       required  single    primary\n"
        "key:                origin      required  single    lookup=dn42.aut-num\n"
        "key:                max-length  optional  single\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "ROUTE6-SCHEMA": (
        "schema:             ROUTE6-SCHEMA\n"
        "ref:                dn42.route6\n"
        "key:                route6      required  single    primary\n"
        "key:                origin      required  single    lookup=dn42.aut-num\n"
        "key:                max-length  optional  single\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "DNS-SCHEMA": (
        "schema:             DNS-SCHEMA\n"
        "ref:                dn42.dns\n"
        "key:                domain      required  single    primary\n"
        "key:                admin-c     required  single    lookup=dn42.person\n"
        "key:                tech-c      required  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                nserver     optional  multiple\n"
        "key:                ds-rdata    optional  multiple\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
    "AS-SET-SCHEMA": (
        "schema:             AS-SET-SCHEMA\n"
        "ref:                dn42.as-set\n"
        "key:                as-set      required  single    primary\n"
        "key:                descr       optional  multiple\n"
        "key:                members     required  multiple\n"
        "key:                admin-c     optional  single    lookup=dn42.person\n"
        "key:                tech-c      optional  single    lookup=dn42.person\n"
        "key:                mnt-by      required  multiple  lookup=dn42.mntner\n"
        "key:                remarks     optional  multiple\n"
        "key:                source      required  single    enum=DN42\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
}

# --- Network allocation policy ---
POLICY = {
    "dn42-policy": (
        "policy:             DN42-ALLOCATION-POLICY\n"
        "descr:              DN42 address allocation and routing policy\n"
        "remarks:            IPv4 allocations MUST fall within 172.20.0.0/14\n"
        "remarks:            IPv6 allocations MUST fall within fd00::/8\n"
        "remarks:            Overlapping inetnum or inet6num allocations are prohibited\n"
        "remarks:            Route origin must reference a registered aut-num object\n"
        "remarks:            Route prefix must be covered by (subnet of) a registered inetnum/inet6num\n"
        "remarks:            Route max-length must be >= the announced prefix length\n"
        "remarks:            AS-SET members must reference registered aut-num or as-set objects\n"
        "remarks:            BGP import filters must implement ROA validation with community tagging\n"
        "remarks:            ROA_INVALID routes must be rejected\n"
        "ipv4-range:         172.20.0.0/14\n"
        "ipv6-range:         fd00::/8\n"
        "roa-community-valid:     64511,1\n"
        "roa-community-invalid:   64511,2\n"
        "roa-community-unknown:   64511,3\n"
        "mnt-by:             DN42-MNT\n"
        "source:             DN42\n"
    ),
}

# --- Registry data objects (some with planted violations) ---
OBJECTS = {
    "mntner": {
        "ALPHA-MNT": (
            "mntner:             ALPHA-MNT\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "auth:               pgp-fingerprint AABBCCDD11223344556677889900AABBCCDDEEFF\n"
            "source:             DN42\n"
        ),
        "BETA-MNT": (
            "mntner:             BETA-MNT\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "auth:               ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBetaKeyData\n"
            "source:             DN42\n"
        ),
        "GAMMA-MNT": (
            "mntner:             GAMMA-MNT\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "auth:               pgp-fingerprint 1122334455667788990011223344556677889900\n"
            "source:             DN42\n"
        ),
        # VIOLATIONS: (1) missing required 'auth' field
        #             (2) admin-c references non-existent person MISSING-DN42
        "DELTA-MNT": (
            "mntner:             DELTA-MNT\n"
            "admin-c:            MISSING-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             DELTA-MNT\n"
            "source:             DN42\n"
        ),
        # VIOLATION: mnt-by references non-existent maintainer NONEXIST-MNT
        "EPSILON-MNT": (
            "mntner:             EPSILON-MNT\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             NONEXIST-MNT\n"
            "auth:               pgp-fingerprint 0011223344556677889900AABBCCDDEEFF001122\n"
            "source:             DN42\n"
        ),
    },

    "person": {
        "ALPHA-DN42": (
            "person:             Alpha User\n"
            "e-mail:             alpha@example.com\n"
            "nic-hdl:            ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        "BETA-DN42": (
            "person:             Beta User\n"
            "e-mail:             beta@example.com\n"
            "nic-hdl:            BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "source:             DN42\n"
        ),
        "GAMMA-DN42": (
            "person:             Gamma User\n"
            "e-mail:             gamma@example.com\n"
            "nic-hdl:            GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             DN42\n"
        ),
    },

    "aut-num": {
        "AS4242420001": (
            "aut-num:            AS4242420001\n"
            "as-name:            ALPHA-AS\n"
            "descr:              Alpha autonomous system\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        "AS4242420002": (
            "aut-num:            AS4242420002\n"
            "as-name:            BETA-AS\n"
            "descr:              Beta autonomous system\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "source:             DN42\n"
        ),
        "AS4242420003": (
            "aut-num:            AS4242420003\n"
            "as-name:            GAMMA-AS\n"
            "descr:              Gamma autonomous system\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             DN42\n"
        ),
        # VIOLATIONS: (1) missing required 'as-name' field
        #             (2) mnt-by references non-existent GHOST-MNT
        "AS4242420004": (
            "aut-num:            AS4242420004\n"
            "descr:              Delta autonomous system\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             GHOST-MNT\n"
            "source:             DN42\n"
        ),
    },

    "inetnum": {
        "172.20.10.0_27": (
            "inetnum:            172.20.10.0 - 172.20.10.31\n"
            "cidr:               172.20.10.0/27\n"
            "netname:            ALPHA-NET-1\n"
            "descr:              Alpha primary allocation\n"
            "country:            DE\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: overlaps with 172.20.10.0/27 (subset)
        "172.20.10.16_28": (
            "inetnum:            172.20.10.16 - 172.20.10.31\n"
            "cidr:               172.20.10.16/28\n"
            "netname:            BETA-NET-1\n"
            "descr:              Beta allocation overlapping alpha\n"
            "country:            US\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        "172.20.50.0_24": (
            "inetnum:            172.20.50.0 - 172.20.50.255\n"
            "cidr:               172.20.50.0/24\n"
            "netname:            BETA-NET-2\n"
            "descr:              Beta secondary allocation\n"
            "country:            US\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        "172.20.100.0_25": (
            "inetnum:            172.20.100.0 - 172.20.100.127\n"
            "cidr:               172.20.100.0/25\n"
            "netname:            GAMMA-NET-1\n"
            "descr:              Gamma primary allocation\n"
            "country:            JP\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: overlaps with 172.20.100.0/25
        "172.20.100.64_26": (
            "inetnum:            172.20.100.64 - 172.20.100.127\n"
            "cidr:               172.20.100.64/26\n"
            "netname:            ALPHA-NET-3\n"
            "descr:              Alpha third allocation overlapping gamma\n"
            "country:            DE\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        "172.21.0.0_24": (
            "inetnum:            172.21.0.0 - 172.21.0.255\n"
            "cidr:               172.21.0.0/24\n"
            "netname:            ALPHA-NET-2\n"
            "descr:              Alpha secondary allocation\n"
            "country:            DE\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # SCHEMA VIOLATION: status PENDING not in enum {ASSIGNED, ALLOCATED}
        "172.22.0.0_24": (
            "inetnum:            172.22.0.0 - 172.22.0.255\n"
            "cidr:               172.22.0.0/24\n"
            "netname:            ZETA-NET\n"
            "descr:              Zeta allocation with invalid status\n"
            "country:            AU\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             PENDING\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: outside valid dn42 range 172.20.0.0/14
        "10.0.0.0_24": (
            "inetnum:            10.0.0.0 - 10.0.0.255\n"
            "cidr:               10.0.0.0/24\n"
            "netname:            INVALID-NET\n"
            "descr:              Allocation in wrong address space\n"
            "country:            XX\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: outside 172.20.0.0/14 (subtle: 172.24 > 172.23.255.255)
        "172.24.0.0_24": (
            "inetnum:            172.24.0.0 - 172.24.0.255\n"
            "cidr:               172.24.0.0/24\n"
            "netname:            EDGE-NET\n"
            "descr:              Allocation just past dn42 boundary\n"
            "remarks:            This looks like it belongs in dn42 but 172.24.x.x is outside /14\n"
            "country:            FR\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
    },

    "inet6num": {
        "fd42:d42:d42::_48": (
            "inet6num:           fd42:0d42:0d42:0000:0000:0000:0000:0000 - fd42:0d42:0d42:ffff:ffff:ffff:ffff:ffff\n"
            "cidr:               fd42:d42:d42::/48\n"
            "netname:            ALPHA-NET6\n"
            "descr:              Alpha IPv6 allocation\n"
            "country:            DE\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: overlaps with fd42:d42:d42::/48
        "fd42:d42:d42:1::_64": (
            "inet6num:           fd42:0d42:0d42:0001:0000:0000:0000:0000 - fd42:0d42:0d42:0001:ffff:ffff:ffff:ffff\n"
            "cidr:               fd42:d42:d42:1::/64\n"
            "netname:            BETA-NET6\n"
            "descr:              Beta IPv6 allocation inside alpha range\n"
            "country:            US\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        "fd86:cafe::_48": (
            "inet6num:           fd86:cafe:0000:0000:0000:0000:0000:0000 - fd86:cafe:0000:ffff:ffff:ffff:ffff:ffff\n"
            "cidr:               fd86:cafe::/48\n"
            "netname:            GAMMA-NET6\n"
            "descr:              Gamma IPv6 allocation\n"
            "country:            JP\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: outside fd00::/8
        "2001:db8::_48": (
            "inet6num:           2001:0db8:0000:0000:0000:0000:0000:0000 - 2001:0db8:0000:ffff:ffff:ffff:ffff:ffff\n"
            "cidr:               2001:db8::/48\n"
            "netname:            INVALID-NET6\n"
            "descr:              Allocation in documentation address space\n"
            "country:            XX\n"
            "admin-c:            GAMMA-DN42\n"
            "tech-c:             GAMMA-DN42\n"
            "mnt-by:             GAMMA-MNT\n"
            "status:             ASSIGNED\n"
            "source:             DN42\n"
        ),
    },

    "route": {
        "172.20.10.0_27": (
            "route:              172.20.10.0/27\n"
            "origin:             AS4242420001\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        "172.20.50.0_24": (
            "route:              172.20.50.0/24\n"
            "origin:             AS4242420002\n"
            "mnt-by:             BETA-MNT\n"
            "source:             DN42\n"
        ),
        "172.20.100.0_25": (
            "route:              172.20.100.0/25\n"
            "origin:             AS4242420003\n"
            "max-length:         25\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             DN42\n"
        ),
        # VIOLATIONS: (1) origin AS4242429999 not registered (broken lookup)
        #             (2) prefix not covered by any inetnum (policy)
        "172.20.200.0_24": (
            "route:              172.20.200.0/24\n"
            "origin:             AS4242429999\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        # POLICY VIOLATION: max-length 20 < prefix length 24
        "172.21.0.0_24": (
            "route:              172.21.0.0/24\n"
            "origin:             AS4242420001\n"
            "max-length:         20\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
    },

    "route6": {
        "fd42:d42:d42::_48": (
            "route6:             fd42:d42:d42::/48\n"
            "origin:             AS4242420001\n"
            "max-length:         48\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        # VIOLATIONS: (1) origin AS4242428888 not registered (broken lookup)
        #             (2) source RIPE not in enum {DN42} (schema)
        "fd86:cafe::_48": (
            "route6:             fd86:cafe::/48\n"
            "origin:             AS4242428888\n"
            "max-length:         48\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             RIPE\n"
        ),
    },

    "dns": {
        "alpha.dn42": (
            "domain:             alpha.dn42\n"
            "admin-c:            ALPHA-DN42\n"
            "tech-c:             ALPHA-DN42\n"
            "mnt-by:             ALPHA-MNT\n"
            "nserver:            ns1.alpha.dn42 172.20.10.1\n"
            "nserver:            ns2.alpha.dn42 fd42:d42:d42::1\n"
            "source:             DN42\n"
        ),
        "beta.dn42": (
            "domain:             beta.dn42\n"
            "admin-c:            BETA-DN42\n"
            "tech-c:             BETA-DN42\n"
            "mnt-by:             BETA-MNT\n"
            "nserver:            ns1.beta.dn42 172.20.50.1\n"
            "source:             DN42\n"
        ),
    },

    "as-set": {
        # Transitive: AS-ALPHA = {AS4242420001} + expand(AS-BETA) = {AS4242420001, AS4242420002, AS4242420003}
        "AS-ALPHA": (
            "as-set:             AS-ALPHA\n"
            "descr:              Alpha network AS set\n"
            "members:            AS4242420001\n"
            "members:            AS-BETA\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
        # Leaf: AS-BETA = {AS4242420002, AS4242420003}
        "AS-BETA": (
            "as-set:             AS-BETA\n"
            "descr:              Beta network AS set\n"
            "members:            AS4242420002\n"
            "members:            AS4242420003\n"
            "mnt-by:             BETA-MNT\n"
            "source:             DN42\n"
        ),
        # Circular: AS-GAMMA -> AS-CYCLE -> AS-GAMMA (must handle gracefully)
        "AS-GAMMA": (
            "as-set:             AS-GAMMA\n"
            "descr:              Gamma network AS set with cycle\n"
            "members:            AS4242420003\n"
            "members:            AS-CYCLE\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             DN42\n"
        ),
        "AS-CYCLE": (
            "as-set:             AS-CYCLE\n"
            "descr:              Cyclical reference set\n"
            "members:            AS4242420004\n"
            "members:            AS-GAMMA\n"
            "mnt-by:             GAMMA-MNT\n"
            "source:             DN42\n"
        ),
        # VIOLATION: member AS-NONEXIST does not exist in as-set/
        "AS-DELTA": (
            "as-set:             AS-DELTA\n"
            "descr:              Delta set with broken reference\n"
            "members:            AS4242420001\n"
            "members:            AS-NONEXIST\n"
            "mnt-by:             ALPHA-MNT\n"
            "source:             DN42\n"
        ),
    },
}


def main():
    # Create schema directory and files
    schema_dir = os.path.join(BASE, "schema")
    os.makedirs(schema_dir, exist_ok=True)
    for name, content in SCHEMAS.items():
        with open(os.path.join(schema_dir, name), "w") as f:
            f.write(content)

    # Create policy directory and file
    policy_dir = os.path.join(BASE, "policy")
    os.makedirs(policy_dir, exist_ok=True)
    for name, content in POLICY.items():
        with open(os.path.join(policy_dir, name), "w") as f:
            f.write(content)

    # Create data object directories and files
    for obj_type, objects in OBJECTS.items():
        type_dir = os.path.join(BASE, obj_type)
        os.makedirs(type_dir, exist_ok=True)
        for name, content in objects.items():
            with open(os.path.join(type_dir, name), "w") as f:
                f.write(content)

    print(f"Registry generated at {BASE}")
    print(f"  schema: {len(SCHEMAS)} definitions")
    print(f"  policy: {len(POLICY)} files")
    for obj_type in sorted(OBJECTS):
        print(f"  {obj_type}: {len(OBJECTS[obj_type])} objects")


if __name__ == "__main__":
    main()
