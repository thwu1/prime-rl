"""
Reference implementation: Systematic futures backtest reconstruction.

Reads data from DuckDB (prices), Parquet (instruments, forecast weights),
YAML (global config), and TOML (trading rules) to reconstruct the pipeline.

"""
import json
import os
import tomllib

import duckdb
import numpy as np
import pandas as pd
import yaml


def main():
    # ── Load prices from DuckDB database ───────────────────────────────────
    conn = duckdb.connect("/app/market.duckdb", read_only=True)

    price_raw = conn.execute(
        "SELECT date, symbol, price FROM daily_prices ORDER BY date, symbol"
    ).fetchdf()

    # ── Load instrument metadata and forecast weights from Parquet ─────────
    inst_df = conn.execute(
        "SELECT * FROM read_parquet('/app/instruments.parquet')"
    ).fetchdf()

    fw_df = conn.execute(
        "SELECT * FROM read_parquet('/app/forecast_weights.parquet')"
    ).fetchdf()

    conn.close()

    instruments = {
        row["symbol"]: {"point_size": row["point_size"], "weight": row["weight"]}
        for _, row in inst_df.iterrows()
    }
    inst_names = sorted(instruments.keys())

    forecast_weights = {}
    for _, row in fw_df.iterrows():
        forecast_weights.setdefault(row["symbol"], {})[row["rule_name"]] = row["weight"]

    price_raw["date"] = pd.to_datetime(price_raw["date"])
    price_df = price_raw.pivot(
        index="date", columns="symbol", values="price"
    ).dropna()

    # ── Load global config from YAML ───────────────────────────────────────
    with open("/app/config.yaml") as f:
        config = yaml.safe_load(f)

    bdays = config["business_days_per_year"]

    # ── Load trading rules and forecast settings from TOML ─────────────────
    with open("/app/rules.toml", "rb") as f:
        rules_config = tomllib.load(f)

    rules = {}
    for rule_def in rules_config["rules"]:
        rules[rule_def["name"]] = {
            "fast_span": rule_def["fast_span"],
            "slow_span": rule_def["slow_span"],
        }
    rule_names = sorted(rules.keys())

    sc_cfg = rules_config["forecast_scalar_estimation"]
    cap = rules_config["forecast_cap"]["value"]

    # ── 1. Mixed volatility estimation ──────────────────────────────────────
    vol_cfg = config["volatility"]
    daily_vols = {}
    for inst in inst_names:
        price_returns = price_df[inst].diff()
        fast_vol = price_returns.ewm(
            span=vol_cfg["fast_span"], min_periods=vol_cfg["min_periods"]
        ).std()
        slow_vol = price_returns.ewm(
            span=vol_cfg["slow_span"], min_periods=vol_cfg["min_periods"]
        ).std()
        daily_vols[inst] = (
            (1 - vol_cfg["proportion_slow"]) * fast_vol
            + vol_cfg["proportion_slow"] * slow_vol
        )

    # ── 2. Raw EWMAC forecasts ──────────────────────────────────────────────
    raw_forecasts = {}
    for inst in inst_names:
        raw_forecasts[inst] = {}
        for rn in rule_names:
            rp = rules[rn]
            fast_ewma = price_df[inst].ewm(span=rp["fast_span"]).mean()
            slow_ewma = price_df[inst].ewm(span=rp["slow_span"]).mean()
            raw_forecasts[inst][rn] = (fast_ewma - slow_ewma) / daily_vols[inst]

    # ── 3. Forecast scalar estimation + capping ─────────────────────────────
    capped_forecasts = {}
    for inst in inst_names:
        capped_forecasts[inst] = {}
        for rn in rule_names:
            raw_fc = raw_forecasts[inst][rn]
            expanding_mean_abs = raw_fc.abs().expanding(
                min_periods=sc_cfg["min_periods"]
            ).mean()
            scalar = sc_cfg["target_abs_forecast"] / expanding_mean_abs
            if sc_cfg["backfill"]:
                scalar = scalar.bfill()
            scaled_fc = raw_fc * scalar
            capped_forecasts[inst][rn] = scaled_fc.clip(-cap, cap)

    # ── 4. FDM estimation ───────────────────────────────────────────────────
    fdm_cfg = config["fdm_estimation"]
    fdms = {}
    for inst in inst_names:
        weights = np.array([forecast_weights[inst][r] for r in rule_names])
        fc_df_inst = pd.DataFrame(
            {r: capped_forecasts[inst][r] for r in rule_names}
        )

        ewm_corr = fc_df_inst.ewm(
            span=fdm_cfg["ewm_span"], min_periods=fdm_cfg["min_periods"]
        ).corr()

        fdm_values = []
        for date in fc_df_inst.index:
            try:
                corr_at_t = ewm_corr.loc[date].values
                if (
                    corr_at_t.shape != (len(rule_names), len(rule_names))
                    or np.any(np.isnan(corr_at_t))
                ):
                    fdm_values.append(np.nan)
                    continue
                wCw = float(weights @ corr_at_t @ weights)
                if wCw > 0:
                    fdm_values.append(
                        min(1.0 / np.sqrt(wCw), fdm_cfg["max_fdm"])
                    )
                else:
                    fdm_values.append(np.nan)
            except (KeyError, ValueError, IndexError):
                fdm_values.append(np.nan)

        fdm_series = pd.Series(fdm_values, index=fc_df_inst.index)
        fdm_series = fdm_series.bfill().fillna(1.0)
        fdms[inst] = fdm_series

    # ── 5. Forecast combination ─────────────────────────────────────────────
    combined_forecasts = {}
    for inst in inst_names:
        weighted_sum = pd.Series(0.0, index=price_df.index)
        for rn in rule_names:
            w = forecast_weights[inst][rn]
            weighted_sum = weighted_sum + w * capped_forecasts[inst][rn]
        combined_forecasts[inst] = weighted_sum * fdms[inst]
    combined_fc_df = pd.DataFrame(combined_forecasts)

    # ── 6. Position sizing ──────────────────────────────────────────────────
    ps_cfg = config["position_sizing"]
    subsystem_positions = {}
    for inst in inst_names:
        annual_risk = (
            daily_vols[inst]
            * np.sqrt(bdays)
            * instruments[inst]["point_size"]
        )
        subsystem_positions[inst] = (
            combined_forecasts[inst] / ps_cfg["average_absolute_forecast"]
        ) * (
            ps_cfg["notional_capital"] * ps_cfg["percentage_vol_target"]
            / annual_risk
        )

    # ── 7. Portfolio allocation ─────────────────────────────────────────────
    idm = config["instrument_div_multiplier"]
    portfolio_positions = {}
    for inst in inst_names:
        iw = instruments[inst]["weight"]
        portfolio_positions[inst] = subsystem_positions[inst] * iw * idm
    positions_df = pd.DataFrame(portfolio_positions)

    # ── 8. P&L calculation ──────────────────────────────────────────────────
    pnl_dict = {}
    for inst in inst_names:
        price_change = price_df[inst].diff()
        pos_lagged = positions_df[inst].shift(1)
        pnl_dict[f"{inst}_pnl"] = (
            pos_lagged * price_change * instruments[inst]["point_size"]
        )
    pnl_df = pd.DataFrame(pnl_dict)
    pnl_df["total_pnl"] = pnl_df.sum(axis=1)

    # ── 9. Statistics ───────────────────────────────────────────────────────
    valid_pnl = pnl_df["total_pnl"].dropna()
    sharpe = float(valid_pnl.mean() / valid_pnl.std() * np.sqrt(bdays))

    equity = ps_cfg["notional_capital"] + valid_pnl.cumsum()
    num_years = len(valid_pnl) / bdays
    annual_return_pct = float(
        ((equity.iloc[-1] / ps_cfg["notional_capital"]) - 1) / num_years * 100
    )

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max * 100
    max_drawdown_pct = float(drawdown.min())

    calmar = (
        float(annual_return_pct / abs(max_drawdown_pct))
        if max_drawdown_pct != 0
        else 0.0
    )

    stats = {
        "sharpe_ratio": round(sharpe, 6),
        "annual_return_pct": round(annual_return_pct, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "calmar_ratio": round(calmar, 6),
    }

    # ── 10. Save outputs ────────────────────────────────────────────────────
    os.makedirs("/app/output", exist_ok=True)

    combined_fc_df.reset_index().rename(columns={"index": "date"}).to_csv(
        "/app/output/combined_forecasts.csv", index=False
    )
    positions_df.reset_index().rename(columns={"index": "date"}).to_csv(
        "/app/output/positions.csv", index=False
    )
    pnl_out = pnl_df.reset_index().rename(columns={"index": "date"})
    pnl_out.to_csv("/app/output/daily_pnl.csv", index=False)

    with open("/app/output/stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    print("Backtest complete.")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
