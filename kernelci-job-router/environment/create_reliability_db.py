#!/usr/bin/env python3
"""Create the lab reliability SQLite database from historical test data."""
import sqlite3

DB_PATH = "/app/reliability.db"

SCORES = [
    ("lava-collabora", "qemu-arm64", 0.95),
    ("lava-collabora", "rk3399-gru-kevin", 0.98),
    ("lava-collabora", "x86-64-pc", 0.95),
    ("lava-collabora", "bcm2711-rpi-4-b", 0.90),
    ("lava-collabora", "sun50i-h6-pine-h64", 0.85),
    ("lava-collabora", "qemu-x86_64", 0.90),
    ("lava-baylibre", "qemu-arm64", 0.80),
    ("lava-baylibre", "rk3399-gru-kevin", 0.80),
    ("lava-baylibre", "db410c", 0.85),
    ("lava-baylibre", "sun50i-h6-pine-h64", 0.70),
    ("lava-baylibre", "meson-g12b-a311d-khadas-vim3", 0.80),
    ("lava-broonie", "qemu-arm64", 0.85),
    ("lava-broonie", "meson-g12b-a311d-khadas-vim3", 0.90),
    ("lava-broonie", "bcm2711-rpi-4-b", 0.85),
    ("lava-broonie", "qemu-x86_64", 0.80),
    ("lava-pengutronix", "qemu-arm64", 0.90),
    ("lava-pengutronix", "rk3399-gru-kevin", 0.85),
    ("lava-pengutronix", "x86-64-pc", 0.90),
    ("lava-pengutronix", "renesas-rzg2l", 0.95),
    ("lava-pengutronix", "imx8mp-evk", 0.95),
    ("lava-pengutronix", "qemu-x86_64", 0.85),
    ("lava-kontron", "x86-64-pc", 0.88),
    ("lava-kontron", "imx8mp-evk", 0.82),
    ("lava-cip", "renesas-rzg2l", 0.92),
    ("lava-riscv", "qemu-riscv64", 0.88),
    ("lava-riscv", "sifive-hifive-unmatched", 0.78),
    ("lava-internal", "qemu-arm64", 0.70),
    ("lava-internal", "x86-64-pc", 0.60),
    ("lava-internal", "qemu-riscv64", 0.65),
    ("lava-internal", "qemu-x86_64", 0.70),
    ("lava-internal", "meson-g12b-a311d-khadas-vim3", 0.65),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS lab_reliability ("
        "  lab_name TEXT NOT NULL,"
        "  device_type TEXT NOT NULL,"
        "  score REAL NOT NULL,"
        "  last_updated TEXT DEFAULT '2025-05-28',"
        "  sample_count INTEGER DEFAULT 100,"
        "  PRIMARY KEY (lab_name, device_type)"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS reliability_metadata ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT"
        ")"
    )
    c.execute("INSERT INTO reliability_metadata VALUES ('version', '2.1')")
    c.execute("INSERT INTO reliability_metadata VALUES ('default_score', '0.50')")
    c.execute("INSERT INTO reliability_metadata VALUES ('computation_window', '30d')")

    for lab, device, score in SCORES:
        c.execute(
            "INSERT INTO lab_reliability (lab_name, device_type, score) "
            "VALUES (?, ?, ?)",
            (lab, device, score),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
