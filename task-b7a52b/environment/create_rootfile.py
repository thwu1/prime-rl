#!/usr/bin/env python3
"""Generate ROOT file containing histogram data for the hypothesis testing task."""
import os
import numpy as np
import uproot

os.makedirs("/app", exist_ok=True)

# Signal region: 10 bins from 100 to 150 GeV
sr_edges = np.array([100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150], dtype=np.float64)

sr_data = np.array([177, 165, 151, 140, 132, 112, 94, 78, 73, 60], dtype=np.float64)
sr_signal = np.array([0.2, 0.8, 3.0, 8.0, 15.0, 15.0, 8.0, 3.0, 0.8, 0.2], dtype=np.float64)
sr_bkg = np.array([180, 160, 142, 126, 112, 100, 89, 79, 70, 62], dtype=np.float64)
sr_bkg_shape_up = np.array([185, 165, 147, 130, 114, 101, 89, 78, 68, 59], dtype=np.float64)
sr_bkg_shape_down = np.array([175, 155, 137, 122, 110, 99, 89, 80, 72, 65], dtype=np.float64)

# Control region: 5 bins from 100 to 150 GeV
cr_edges = np.array([100, 110, 120, 130, 140, 150], dtype=np.float64)
cr_data = np.array([844, 728, 593, 501, 382], dtype=np.float64)
cr_bkg = np.array([850, 720, 600, 490, 390], dtype=np.float64)

with uproot.recreate("/app/observations.root") as f:
    f["signal_region/data_obs"] = (sr_data, sr_edges)
    f["signal_region/signal_nominal"] = (sr_signal, sr_edges)
    f["signal_region/bkg_nominal"] = (sr_bkg, sr_edges)
    f["signal_region/bkg_shape_up"] = (sr_bkg_shape_up, sr_edges)
    f["signal_region/bkg_shape_down"] = (sr_bkg_shape_down, sr_edges)
    f["control_region/data_obs"] = (cr_data, cr_edges)
    f["control_region/bkg_nominal"] = (cr_bkg, cr_edges)

print("Created /app/observations.root")
