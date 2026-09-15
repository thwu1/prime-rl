"""I/O utilities for multi-reservoir cascade data."""
from datetime import date, timedelta

import netCDF4 as nc


def load_cascade_data(filepath="/app/data/cascade.nc"):
    """Load cascade reservoir data from NetCDF.

    Returns:
        reservoir_params: list of 3 dicts, one per reservoir
        reach_params: list of 2 dicts with keys 'K' and 'x'
        dates: list of date objects
        lateral_inflows: list of 3 lists of floats (m3/s)
        metadata: dict with global attributes
    """
    ds = nc.Dataset(filepath, "r")

    n_res = int(ds.getncattr("n_reservoirs"))
    n_reaches = int(ds.getncattr("n_reaches"))
    n_days = int(ds.getncattr("n_days"))
    start_str = str(ds.getncattr("start_date"))
    demand = float(ds.getncattr("demand_target_cms"))

    param_names = [
        "GRanD_CAP_MCM", "Obs_MEANFLOW_CUMECS", "initial_storage_MCM",
        "NORhi_min", "NORhi_max", "NORhi_alpha", "NORhi_beta", "NORhi_mu",
        "NORlo_min", "NORlo_max", "NORlo_alpha", "NORlo_beta", "NORlo_mu",
        "Release_min", "Release_max",
        "Release_alpha1", "Release_alpha2", "Release_beta1", "Release_beta2",
        "Release_p1", "Release_p2", "Release_c",
    ]

    reservoir_params = []
    for r in range(n_res):
        params = {}
        for name in param_names:
            params[name] = float(ds.variables[name][r])
        reservoir_params.append(params)

    reach_params = []
    for i in range(n_reaches):
        reach_params.append({
            "K": float(ds.variables["reach_K_days"][i]),
            "x": float(ds.variables["reach_x"][i]),
        })

    lateral_inflows = []
    for r in range(n_res):
        inflows = [float(x) for x in ds.variables["inflow_cms"][r, :]]
        lateral_inflows.append(inflows)

    start = date.fromisoformat(start_str)
    dates = [start + timedelta(days=i) for i in range(n_days)]

    metadata = {
        "start_date": start_str,
        "n_days": n_days,
        "n_reservoirs": n_res,
        "n_reaches": n_reaches,
        "demand_target_cms": demand,
    }

    ds.close()
    return reservoir_params, reach_params, dates, lateral_inflows, metadata
