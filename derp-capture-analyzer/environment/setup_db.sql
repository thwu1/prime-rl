CREATE TABLE relays (
    relay_id TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    fqdn TEXT NOT NULL,
    capacity_peers INTEGER NOT NULL
);

CREATE TABLE peer_policies (
    peer_key_hex TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    allowed_relay_ids TEXT NOT NULL,
    allowed_dest_keys TEXT,
    max_session_count INTEGER DEFAULT 1
);

CREATE TABLE blocklist (
    peer_key_hex TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    added_at TEXT NOT NULL
);

INSERT INTO relays VALUES ('relay-alpha', 'us-east', 'derp1.example.com', 100);
INSERT INTO relays VALUES ('relay-beta', 'us-west', 'derp2.example.com', 100);
INSERT INTO relays VALUES ('relay-gamma', 'eu-west', 'derp3.example.com', 50);
