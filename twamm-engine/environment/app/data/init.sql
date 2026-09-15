
-- Schema --

CREATE TABLE IF NOT EXISTS pools (
    pool_id   TEXT PRIMARY KEY,
    initial_x REAL NOT NULL,
    initial_y REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    pool_id     TEXT NOT NULL REFERENCES pools(pool_id),
    description TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT    NOT NULL,
    scenario_id      TEXT    NOT NULL REFERENCES scenarios(scenario_id),
    sell_token       TEXT    NOT NULL CHECK(sell_token IN ('x', 'y')),
    total_sell_amount REAL   NOT NULL,
    start_block      INTEGER NOT NULL,
    end_block        INTEGER NOT NULL,
    PRIMARY KEY (order_id, scenario_id)
);

-- Pool definitions --

INSERT INTO pools VALUES ('pool_a', 1000.0, 4000.0);
INSERT INTO pools VALUES ('pool_b', 4000.0, 1000.0);
INSERT INTO pools VALUES ('pool_c', 5000.0, 5000.0);
INSERT INTO pools VALUES ('pool_d', 10000.0, 10000.0);
INSERT INTO pools VALUES ('pool_e', 20000.0, 5000.0);
INSERT INTO pools VALUES ('pool_f', 8000.0, 2000.0);
INSERT INTO pools VALUES ('pool_g', 3000.0, 7000.0);
INSERT INTO pools VALUES ('pool_h', 20000.0, 20000.0);

-- Scenarios --

INSERT INTO scenarios VALUES ('s1',  'pool_a', 'Single-sided X selling');
INSERT INTO scenarios VALUES ('s2',  'pool_b', 'Single-sided Y selling');
INSERT INTO scenarios VALUES ('s3',  'pool_c', 'Symmetric equilibrium');
INSERT INTO scenarios VALUES ('s4',  'pool_d', 'Asymmetric two-sided case A');
INSERT INTO scenarios VALUES ('s5',  'pool_e', 'Asymmetric two-sided case B');
INSERT INTO scenarios VALUES ('s6',  'pool_d', 'Multi-interval order expiry');
INSERT INTO scenarios VALUES ('s7',  'pool_d', 'Pool sharing proportional split');
INSERT INTO scenarios VALUES ('s8',  'pool_h', 'Staggered three-interval');
INSERT INTO scenarios VALUES ('s9',  'pool_c', 'Zero-duration edge case');
INSERT INTO scenarios VALUES ('s10', 'pool_f', 'Single order no opposition');
INSERT INTO scenarios VALUES ('s11', 'pool_g', 'Empty order list');

-- Orders --

-- s1: single X seller
INSERT INTO orders VALUES ('o1', 's1', 'x', 1000.0, 0, 10);

-- s2: single Y seller
INSERT INTO orders VALUES ('o1', 's2', 'y', 1000.0, 0, 10);

-- s3: symmetric equilibrium
INSERT INTO orders VALUES ('xsell', 's3', 'x', 10000.0, 0, 100);
INSERT INTO orders VALUES ('ysell', 's3', 'y', 10000.0, 0, 100);

-- s4: asymmetric, x_rate > y_rate
INSERT INTO orders VALUES ('xsell', 's4', 'x', 20000.0, 0, 50);
INSERT INTO orders VALUES ('ysell', 's4', 'y', 5000.0,  0, 50);

-- s5: asymmetric, y_rate > x_rate
INSERT INTO orders VALUES ('xsell', 's5', 'x', 4000.0,  0, 80);
INSERT INTO orders VALUES ('ysell', 's5', 'y', 16000.0, 0, 80);

-- s6: order expiry creates two intervals
INSERT INTO orders VALUES ('xsell', 's6', 'x', 10000.0, 0, 50);
INSERT INTO orders VALUES ('ysell', 's6', 'y', 10000.0, 0, 100);

-- s7: two X sellers + one Y seller (proportional sharing)
INSERT INTO orders VALUES ('x1', 's7', 'x', 10000.0, 0, 100);
INSERT INTO orders VALUES ('x2', 's7', 'x', 30000.0, 0, 100);
INSERT INTO orders VALUES ('y1', 's7', 'y', 20000.0, 0, 100);

-- s8: staggered start/end blocks create three intervals
INSERT INTO orders VALUES ('x1', 's8', 'x', 5000.0,  0,  50);
INSERT INTO orders VALUES ('x2', 's8', 'x', 15000.0, 0,  100);
INSERT INTO orders VALUES ('y1', 's8', 'y', 10000.0, 20, 100);

-- s9: zero-duration order + normal order
INSERT INTO orders VALUES ('zero', 's9', 'x', 1000.0, 10, 10);
INSERT INTO orders VALUES ('real', 's9', 'x', 2000.0, 0,  20);

-- s10: single order with no opposition
INSERT INTO orders VALUES ('only', 's10', 'y', 3000.0, 5, 35);

-- s11: no orders (empty scenario)
