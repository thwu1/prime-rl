"""Data loading from SQLite database."""
import pandas as pd
import sqlite3

DB_PATH = '/app/market.db'


def _conn():
    return sqlite3.connect(DB_PATH)


def load_prices(instrument):
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, price FROM prices WHERE instrument = ? ORDER BY date",
        conn, params=(instrument,), parse_dates=['date'])
    conn.close()
    return df.set_index('date')['price']


def load_carry_data(instrument):
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, price, carry_price FROM carry_prices "
        "WHERE instrument = ? ORDER BY date",
        conn, params=(instrument,), parse_dates=['date'])
    conn.close()
    return df.set_index('date')


def load_fx_rate(instrument_currency, base_currency, index):
    if instrument_currency == base_currency:
        return pd.Series(1.0, index=index, name='fx')
    pair = f"{base_currency}_{instrument_currency}"
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, rate FROM fx_rates WHERE pair = ? ORDER BY date",
        conn, params=(pair,), parse_dates=['date'])
    conn.close()
    if df.empty:
        return pd.Series(1.0, index=index, name='fx')
    return df.set_index('date')['rate'].reindex(index).ffill()


def load_instrument_config():
    conn = _conn()
    df = pd.read_sql_query("SELECT * FROM instruments", conn)
    conn.close()
    return df
