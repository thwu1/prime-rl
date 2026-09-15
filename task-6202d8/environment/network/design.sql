-- Network Design Specification Database
-- Contains the intended (correct) configuration parameters for the enterprise network.
-- Actual router configurations may deviate from this specification.

CREATE TABLE design_ospf_links (
    link_id TEXT PRIMARY KEY,
    router_a TEXT NOT NULL,
    interface_a TEXT NOT NULL,
    router_b TEXT NOT NULL,
    interface_b TEXT NOT NULL,
    area INTEGER NOT NULL,
    hello_interval INTEGER NOT NULL DEFAULT 10,
    dead_interval INTEGER NOT NULL DEFAULT 40,
    ip_mtu INTEGER NOT NULL DEFAULT 1500,
    cost_a INTEGER NOT NULL,
    cost_b INTEGER NOT NULL
);

INSERT INTO design_ospf_links VALUES ('L1', 'R1', 'GigabitEthernet0/0', 'R2', 'GigabitEthernet0/0', 0, 10, 40, 1500, 10, 10);
INSERT INTO design_ospf_links VALUES ('L2', 'R1', 'GigabitEthernet0/1', 'R3', 'GigabitEthernet0/0', 0, 10, 40, 1500, 10, 10);
INSERT INTO design_ospf_links VALUES ('L3', 'R2', 'GigabitEthernet0/1', 'R4', 'GigabitEthernet0/0', 10, 10, 40, 1500, 5, 5);
INSERT INTO design_ospf_links VALUES ('L4', 'R3', 'GigabitEthernet0/1', 'R5', 'GigabitEthernet0/0', 20, 10, 40, 1500, 5, 5);
INSERT INTO design_ospf_links VALUES ('L5', 'R2', 'GigabitEthernet0/2', 'R3', 'GigabitEthernet0/2', 0, 10, 40, 1500, 500, 500);

CREATE TABLE design_ospf_areas (
    router TEXT NOT NULL,
    area INTEGER NOT NULL,
    area_type TEXT NOT NULL DEFAULT 'normal',
    PRIMARY KEY (router, area)
);

INSERT INTO design_ospf_areas VALUES ('R3', 20, 'nssa');
INSERT INTO design_ospf_areas VALUES ('R5', 20, 'nssa');

CREATE TABLE design_bgp_sessions (
    router TEXT NOT NULL,
    neighbor_ip TEXT NOT NULL,
    remote_as INTEGER NOT NULL,
    session_type TEXT NOT NULL,
    update_source TEXT,
    is_rr_client INTEGER DEFAULT 0,
    next_hop_self INTEGER DEFAULT 0,
    PRIMARY KEY (router, neighbor_ip)
);

INSERT INTO design_bgp_sessions VALUES ('R1', '10.0.0.2', 65001, 'ibgp', 'Loopback0', 1, 1);
INSERT INTO design_bgp_sessions VALUES ('R1', '10.0.0.3', 65001, 'ibgp', 'Loopback0', 1, 1);
INSERT INTO design_bgp_sessions VALUES ('R1', '10.99.1.2', 65100, 'ebgp', NULL, 0, 0);
INSERT INTO design_bgp_sessions VALUES ('R2', '10.0.0.1', 65001, 'ibgp', 'Loopback0', 0, 0);
INSERT INTO design_bgp_sessions VALUES ('R3', '10.0.0.1', 65001, 'ibgp', 'Loopback0', 0, 0);
INSERT INTO design_bgp_sessions VALUES ('R6', '10.99.1.1', 65001, 'ebgp', NULL, 0, 0);

CREATE TABLE design_redistribution (
    router TEXT NOT NULL,
    from_protocol TEXT NOT NULL,
    to_protocol TEXT NOT NULL,
    route_map TEXT NOT NULL,
    tag INTEGER,
    PRIMARY KEY (router, from_protocol, to_protocol)
);

INSERT INTO design_redistribution VALUES ('R4', 'eigrp 100', 'ospf 1', 'EIGRP-TO-OSPF', 100);
INSERT INTO design_redistribution VALUES ('R4', 'ospf 1', 'eigrp 100', 'OSPF-TO-EIGRP', NULL);
INSERT INTO design_redistribution VALUES ('R5', 'eigrp 200', 'ospf 1', 'EIGRP-TO-OSPF', 200);
INSERT INTO design_redistribution VALUES ('R5', 'ospf 1', 'eigrp 200', 'OSPF-TO-EIGRP', NULL);

CREATE TABLE design_security (
    router TEXT NOT NULL,
    feature TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    policy_name TEXT,
    PRIMARY KEY (router, feature)
);

INSERT INTO design_security VALUES ('R1', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R2', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R3', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R4', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R5', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R6', 'copp', 1, 'COPP-POLICY');
INSERT INTO design_security VALUES ('R1', 'vty_acl', 1, '99');
INSERT INTO design_security VALUES ('R2', 'vty_acl', 1, '99');
INSERT INTO design_security VALUES ('R3', 'vty_acl', 1, '99');
INSERT INTO design_security VALUES ('R4', 'vty_acl', 1, '99');
INSERT INTO design_security VALUES ('R5', 'vty_acl', 1, '99');
INSERT INTO design_security VALUES ('R6', 'vty_acl', 1, '99');

CREATE TABLE ip_plan (
    router TEXT NOT NULL,
    interface TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    prefix_length INTEGER NOT NULL,
    subnet TEXT NOT NULL,
    PRIMARY KEY (router, interface)
);

INSERT INTO ip_plan VALUES ('R1', 'Loopback0', '10.0.0.1', 32, '10.0.0.1/32');
INSERT INTO ip_plan VALUES ('R1', 'GigabitEthernet0/0', '10.1.12.1', 30, '10.1.12.0/30');
INSERT INTO ip_plan VALUES ('R1', 'GigabitEthernet0/1', '10.1.13.1', 30, '10.1.13.0/30');
INSERT INTO ip_plan VALUES ('R1', 'GigabitEthernet0/2', '10.99.1.1', 30, '10.99.1.0/30');
INSERT INTO ip_plan VALUES ('R2', 'Loopback0', '10.0.0.2', 32, '10.0.0.2/32');
INSERT INTO ip_plan VALUES ('R2', 'GigabitEthernet0/0', '10.1.12.2', 30, '10.1.12.0/30');
INSERT INTO ip_plan VALUES ('R2', 'GigabitEthernet0/1', '10.1.24.1', 30, '10.1.24.0/30');
INSERT INTO ip_plan VALUES ('R2', 'GigabitEthernet0/2', '10.1.23.1', 30, '10.1.23.0/30');
INSERT INTO ip_plan VALUES ('R3', 'Loopback0', '10.0.0.3', 32, '10.0.0.3/32');
INSERT INTO ip_plan VALUES ('R3', 'GigabitEthernet0/0', '10.1.13.2', 30, '10.1.13.0/30');
INSERT INTO ip_plan VALUES ('R3', 'GigabitEthernet0/1', '10.1.35.1', 30, '10.1.35.0/30');
INSERT INTO ip_plan VALUES ('R3', 'GigabitEthernet0/2', '10.1.23.2', 30, '10.1.23.0/30');
INSERT INTO ip_plan VALUES ('R4', 'Loopback0', '10.0.0.4', 32, '10.0.0.4/32');
INSERT INTO ip_plan VALUES ('R4', 'GigabitEthernet0/0', '10.1.24.2', 30, '10.1.24.0/30');
INSERT INTO ip_plan VALUES ('R4', 'GigabitEthernet0/1', '10.4.1.1', 24, '10.4.1.0/24');
INSERT INTO ip_plan VALUES ('R4', 'GigabitEthernet0/2', '10.4.2.1', 24, '10.4.2.0/24');
INSERT INTO ip_plan VALUES ('R5', 'Loopback0', '10.0.0.5', 32, '10.0.0.5/32');
INSERT INTO ip_plan VALUES ('R5', 'GigabitEthernet0/0', '10.1.35.2', 30, '10.1.35.0/30');
INSERT INTO ip_plan VALUES ('R5', 'GigabitEthernet0/1', '10.5.1.1', 24, '10.5.1.0/24');
INSERT INTO ip_plan VALUES ('R5', 'GigabitEthernet0/2', '10.5.2.1', 24, '10.5.2.0/24');
INSERT INTO ip_plan VALUES ('R6', 'Loopback0', '172.16.0.1', 32, '172.16.0.1/32');
INSERT INTO ip_plan VALUES ('R6', 'GigabitEthernet0/0', '10.99.1.2', 24, '10.99.1.0/24');
INSERT INTO ip_plan VALUES ('R6', 'Loopback1', '172.16.1.1', 32, '172.16.1.1/32');

CREATE TABLE sla_requirements (
    flow_id TEXT PRIMARY KEY,
    source_prefix TEXT NOT NULL,
    dest_prefix TEXT NOT NULL,
    max_ospf_cost INTEGER,
    description TEXT NOT NULL
);

INSERT INTO sla_requirements VALUES ('flow_a', '10.4.1.0/24', '10.5.1.0/24', 40, 'Branch West LAN to Branch East LAN');
INSERT INTO sla_requirements VALUES ('flow_b', '10.4.1.0/24', '10.0.0.1/32', 20, 'Branch West LAN to Core router loopback');
INSERT INTO sla_requirements VALUES ('flow_c', '10.5.1.0/24', '172.16.0.0/16', NULL, 'Branch East LAN to ISP prefix');
