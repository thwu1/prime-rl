#!/usr/bin/env python3
"""Create the AMM market database with pool definitions."""
import sqlite3

DB_PATH = "/app/market.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE tokens (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            decimals INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE pools (
            id TEXT PRIMARY KEY,
            pool_type TEXT NOT NULL,
            token_a TEXT NOT NULL,
            token_b TEXT NOT NULL,
            fee_bps INTEGER NOT NULL,
            FOREIGN KEY (token_a) REFERENCES tokens(symbol),
            FOREIGN KEY (token_b) REFERENCES tokens(symbol)
        )
    """)

    c.execute("""
        CREATE TABLE pool_reserves (
            pool_id TEXT PRIMARY KEY,
            reserve_a REAL NOT NULL,
            reserve_b REAL NOT NULL,
            last_updated INTEGER NOT NULL,
            FOREIGN KEY (pool_id) REFERENCES pools(id)
        )
    """)

    c.execute("""
        CREATE TABLE pool_params (
            pool_id TEXT NOT NULL,
            param_name TEXT NOT NULL,
            param_value REAL NOT NULL,
            PRIMARY KEY (pool_id, param_name),
            FOREIGN KEY (pool_id) REFERENCES pools(id)
        )
    """)

    c.execute("""
        CREATE TABLE recent_swaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_id TEXT NOT NULL,
            block_number INTEGER NOT NULL,
            token_in TEXT NOT NULL,
            amount_in REAL NOT NULL,
            amount_out REAL NOT NULL,
            FOREIGN KEY (pool_id) REFERENCES pools(id)
        )
    """)

    # Tokens
    tokens = [
        ("USDC", "USD Coin", 6),
        ("WETH", "Wrapped Ether", 18),
        ("WBTC", "Wrapped Bitcoin", 8),
        ("DAI", "Dai Stablecoin", 18),
        ("LINK", "Chainlink", 18),
        ("AAVE", "Aave Token", 18),
    ]
    c.executemany("INSERT INTO tokens VALUES (?, ?, ?)", tokens)

    # Pools
    pools = [
        ("cp-usdc-weth", "ConstantProduct", "USDC", "WETH", 30),
        ("cp-weth-wbtc", "ConstantProduct", "WETH", "WBTC", 30),
        ("cp-wbtc-usdc", "ConstantProduct", "WBTC", "USDC", 30),
        ("ss-usdc-dai", "StableSwap", "USDC", "DAI", 4),
        ("cp-dai-weth", "ConstantProduct", "DAI", "WETH", 30),
        ("wp-weth-wbtc", "WeightedProduct", "WETH", "WBTC", 25),
        ("cp-link-weth", "ConstantProduct", "LINK", "WETH", 30),
        ("cp-link-usdc", "ConstantProduct", "LINK", "USDC", 30),
        ("cp-aave-weth", "ConstantProduct", "AAVE", "WETH", 30),
        ("cp-aave-usdc", "ConstantProduct", "AAVE", "USDC", 30),
        ("cp-dai-link", "ConstantProduct", "DAI", "LINK", 30),
        ("cp-aave-link", "ConstantProduct", "AAVE", "LINK", 30),
    ]
    c.executemany("INSERT INTO pools VALUES (?, ?, ?, ?, ?)", pools)

    # Reserves
    reserves = [
        ("cp-usdc-weth", 2000000.0, 1000.0, 1700000000),
        ("cp-weth-wbtc", 620.0, 20.0, 1700000000),
        ("cp-wbtc-usdc", 50.0, 3200000.0, 1700000000),
        ("ss-usdc-dai", 5000000.0, 5100000.0, 1700000000),
        ("cp-dai-weth", 1850000.0, 1000.0, 1700000000),
        ("wp-weth-wbtc", 400.0, 5.5, 1700000000),
        ("cp-link-weth", 100000.0, 500.0, 1700000000),
        ("cp-link-usdc", 80000.0, 800000.0, 1700000000),
        ("cp-aave-weth", 5000.0, 250.0, 1700000000),
        ("cp-aave-usdc", 4000.0, 400000.0, 1700000000),
        ("cp-dai-link", 200000.0, 20000.0, 1700000000),
        ("cp-aave-link", 3000.0, 30000.0, 1700000000),
    ]
    c.executemany("INSERT INTO pool_reserves VALUES (?, ?, ?, ?)", reserves)

    # Pool-specific parameters
    params = [
        ("ss-usdc-dai", "amp_factor", 200.0),
        ("wp-weth-wbtc", "weight_a", 0.7),
        ("wp-weth-wbtc", "weight_b", 0.3),
    ]
    c.executemany("INSERT INTO pool_params VALUES (?, ?, ?)", params)

    # Recent swap history (realistic noise data)
    swaps = [
        ("cp-usdc-weth", 19000001, "USDC", 50000.0, 24.85),
        ("cp-usdc-weth", 19000002, "WETH", 5.0, 9940.18),
        ("cp-weth-wbtc", 19000003, "WETH", 10.0, 0.3175),
        ("ss-usdc-dai", 19000004, "USDC", 100000.0, 100019.8),
        ("ss-usdc-dai", 19000005, "DAI", 50000.0, 49990.1),
        ("cp-dai-weth", 19000006, "DAI", 37000.0, 19.6),
        ("cp-wbtc-usdc", 19000007, "WBTC", 1.0, 63360.0),
        ("cp-link-weth", 19000008, "LINK", 500.0, 2.49),
        ("cp-link-usdc", 19000009, "USDC", 10000.0, 990.1),
        ("cp-aave-weth", 19000010, "AAVE", 100.0, 4.95),
        ("cp-aave-usdc", 19000011, "AAVE", 50.0, 4950.5),
        ("cp-dai-link", 19000012, "DAI", 5000.0, 495.05),
        ("cp-usdc-weth", 19000013, "USDC", 20000.0, 9.95),
        ("cp-weth-wbtc", 19000014, "WBTC", 0.5, 15.24),
        ("ss-usdc-dai", 19000015, "USDC", 200000.0, 200039.5),
        ("cp-dai-weth", 19000016, "WETH", 2.0, 3696.0),
        ("cp-wbtc-usdc", 19000017, "USDC", 100000.0, 1.554),
        ("cp-aave-link", 19000018, "AAVE", 100.0, 990.1),
        ("cp-link-weth", 19000019, "WETH", 1.0, 199.4),
        ("cp-aave-usdc", 19000020, "USDC", 50000.0, 490.2),
    ]
    c.executemany(
        "INSERT INTO recent_swaps (pool_id, block_number, token_in, amount_in, amount_out) VALUES (?, ?, ?, ?, ?)",
        swaps,
    )

    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
