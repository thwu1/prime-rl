#!/usr/bin/env python3

"""Solution for the CMIP6 ensemble evaluation and weighted projection task."""

import json
import numpy as np
import zarr


def main():
    with open("/app/data/catalog.json") as f:
        catalog = json.load(f)

    # Models are every catalog entry except the reference
    models = sorted(k for k in catalog if k != "reference")

    # Load reference historical temperature (already in degC)
    ref = zarr.open(catalog["reference"]["historical"], "r")
    ref_tas = ref["tas"][:]
    ref_lat = ref["lat"][:]
    w_lat = np.cos(np.deg2rad(ref_lat))
    n_time = ref_tas.shape[0]

    results = {
        "model_diagnostics": {},
        "skill_metrics": {},
        "model_ranking": [],
        "ensemble_weights": {},
        "equal_weight_rmse": None,
        "weighted_ensemble_rmse": None,
        "weighted_beats_equal": None,
        "projected_warming": {},
    }

    hist_corrected = {}
    ssp_corrected = {}
    rmse_vals = {}

    for model in models:
        # ---- Load historical ----
        h = zarr.open(catalog[model]["historical"], "r")
        h_tas = h["tas"][:]
        h_lon = h["lon"][:]
        meta_unit = str(h["tas"].attrs["units"])

        # Infer true unit from physical plausibility of value range
        med = float(np.nanmedian(h_tas))
        inferred = "K" if med > 200 else "degC"
        needs_fix = meta_unit != inferred

        # Humidity diagnostics
        hurs_meta_unit = str(h["hurs"].attrs.get("units", ""))
        hurs_data = h["hurs"][:]
        hurs_med = float(np.nanmedian(hurs_data))
        hurs_fractional = bool(hurs_med < 2.0)

        # Longitude convention
        lon_conv = "0_to_360" if float(h_lon.min()) >= 0 else "standard"

        # NaN detection
        has_nan = bool(np.isnan(h_tas).any())
        nan_months = 0
        if has_nan:
            nan_months = int(
                np.any(np.isnan(h_tas.reshape(h_tas.shape[0], -1)), axis=1).sum()
            )

        results["model_diagnostics"][model] = {
            "tas_metadata_unit": meta_unit,
            "tas_inferred_unit": inferred,
            "needs_unit_correction": needs_fix,
            "hurs_metadata_unit": hurs_meta_unit,
            "hurs_is_fractional": hurs_fractional,
            "lon_convention": lon_conv,
            "tas_has_nan": has_nan,
            "tas_nan_month_count": nan_months,
        }

        # Convert to degC using INFERRED unit (not metadata!)
        h_c = (h_tas - 273.15) if inferred == "K" else h_tas.copy()

        # Remap 0-to-360 longitude to standard (-180..180) convention
        if lon_conv == "0_to_360":
            std_lon = np.where(h_lon > 180, h_lon - 360, h_lon)
            order = np.argsort(std_lon)
            h_c = h_c[:, :, order]

        hist_corrected[model] = h_c

        # ---- Skill metrics vs reference ----
        diff = h_c - ref_tas
        # Valid timesteps: no NaN anywhere in the spatial field
        valid_t = ~np.any(np.isnan(diff.reshape(diff.shape[0], -1)), axis=1)
        dv = diff[valid_t]

        # Mean bias: lon mean -> cos-lat weighted lat mean -> time mean
        lon_mean = dv.mean(axis=2)  # (n_valid, nlat)
        bias_t = np.average(lon_mean, weights=w_lat, axis=1)  # (n_valid,)
        mean_bias = float(bias_t.mean())

        # RMSE: lon mean of sq diff -> cos-lat weighted -> sqrt of time mean
        sq = dv ** 2
        sq_lon = sq.mean(axis=2)
        mse_t = np.average(sq_lon, weights=w_lat, axis=1)
        rmse = float(np.sqrt(mse_t.mean()))

        # Pattern correlation: nanmean over time, then cos-lat weighted Pearson
        m_tmean = np.nanmean(h_c, axis=0)  # (nlat, nlon)
        r_tmean = np.nanmean(ref_tas, axis=0)
        w2 = w_lat[:, None] * np.ones(m_tmean.shape[1])
        ws = w2.sum()
        mx = (w2 * m_tmean).sum() / ws
        rx = (w2 * r_tmean).sum() / ws
        num = (w2 * (m_tmean - mx) * (r_tmean - rx)).sum()
        dm = (w2 * (m_tmean - mx) ** 2).sum()
        dr = (w2 * (r_tmean - rx) ** 2).sum()
        pcorr = float(num / np.sqrt(dm * dr))

        results["skill_metrics"][model] = {
            "mean_bias": round(mean_bias, 4),
            "rmse": round(rmse, 4),
            "pattern_correlation": round(pcorr, 4),
        }
        rmse_vals[model] = rmse

        # ---- Load SSP585 ----
        s = zarr.open(catalog[model]["ssp585"], "r")
        s_tas = s["tas"][:]
        s_lon = s["lon"][:]
        s_med = float(np.nanmedian(s_tas))
        s_inf = "K" if s_med > 200 else "degC"
        s_c = (s_tas - 273.15) if s_inf == "K" else s_tas.copy()
        if lon_conv == "0_to_360":
            std_lon = np.where(s_lon > 180, s_lon - 360, s_lon)
            order = np.argsort(std_lon)
            s_c = s_c[:, :, order]
        ssp_corrected[model] = s_c

    # ---- Model ranking (ascending RMSE) ----
    ranking = sorted(models, key=lambda m: rmse_vals[m])
    results["model_ranking"] = ranking

    # ---- Inverse-RMSE ensemble weights ----
    inv = {m: 1.0 / rmse_vals[m] for m in models}
    inv_sum = sum(inv.values())
    weights = {m: inv[m] / inv_sum for m in models}
    results["ensemble_weights"] = {m: round(weights[m], 4) for m in models}

    # ---- Ensemble RMSE (equal-weight and inverse-RMSE-weighted) ----
    eq_mse_list = []
    wt_mse_list = []

    for t in range(n_time):
        avail = [m for m in models if not np.any(np.isnan(hist_corrected[m][t]))]
        if not avail:
            continue

        # Equal-weight ensemble mean
        eq = np.mean([hist_corrected[m][t] for m in avail], axis=0)
        ed = (eq - ref_tas[t]) ** 2
        eq_mse_list.append(float(np.average(ed.mean(axis=1), weights=w_lat)))

        # Weighted ensemble mean (renormalize among available models)
        wa = {m: inv[m] for m in avail}
        wa_s = sum(wa.values())
        wt = sum(wa[m] / wa_s * hist_corrected[m][t] for m in avail)
        wd = (wt - ref_tas[t]) ** 2
        wt_mse_list.append(float(np.average(wd.mean(axis=1), weights=w_lat)))

    eq_rmse = float(np.sqrt(np.mean(eq_mse_list)))
    wt_rmse = float(np.sqrt(np.mean(wt_mse_list)))

    results["equal_weight_rmse"] = round(eq_rmse, 4)
    results["weighted_ensemble_rmse"] = round(wt_rmse, 4)
    results["weighted_beats_equal"] = bool(wt_rmse < eq_rmse)

    # ---- Projected warming ----
    for model in models:
        h_last = np.nanmean(hist_corrected[model][-120:], axis=0)  # (nlat, nlon)
        s_last = np.nanmean(ssp_corrected[model][-120:], axis=0)
        diff = s_last - h_last
        lon_mean = diff.mean(axis=1)  # (nlat,)
        warming = float(np.average(lon_mean, weights=w_lat))
        results["projected_warming"][model] = round(warming, 4)

    # Weighted ensemble warming
    ens_w = sum(results["projected_warming"][m] * weights[m] for m in models)
    results["projected_warming"]["weighted_ensemble"] = round(float(ens_w), 4)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
