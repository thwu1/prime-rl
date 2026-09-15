#!/usr/bin/env python3
"""Generate HDF5 solver data, experimental CSV, and reference TOML for DPW-8 task."""
import h5py
import numpy as np
import os

os.makedirs("/app/data", exist_ok=True)

alphas = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CL_base = np.array([0.17783, 0.31918, 0.46611, 0.60689, 0.68657, 0.73105])
CD_base = np.array([0.01874, 0.02127, 0.02585, 0.03601, 0.05195, 0.06842])
CM_base = np.array([0.05477, 0.00446, -0.03992, -0.07560, -0.05971, -0.06316])

solver_defs = {
    "S001": {"name":"FUN3D","turb":"SA-neg","gl":3,"gs":16000000,
             "dCL":[.001,.0008,.0015,.0005,-.001,-.0025],
             "dCD":[.00005,.00008,.00012,.00015,.0002,.00025],
             "dCM":[-.0005,-.0003,.0002,.0008,.0012,.001]},
    "S002": {"name":"CFL3D","turb":"SA-neg","gl":3,"gs":12800000,
             "dCL":[-.0015,-.0012,-.0008,.001,.0022,.0018],
             "dCD":[.0001,.00005,-.00005,-.0001,.00005,.00015],
             "dCM":[.0008,.0005,-.0003,-.001,-.0005,.0008]},
    "S003": {"name":"OVERFLOW","turb":"SST-V","gl":3,"gs":16200000,
             "dCL":[.0025,.002,.001,-.0008,-.0015,-.003],
             "dCD":[-.00008,-.00005,.00003,.0001,.00018,.0003],
             "dCM":[-.001,-.0008,.0005,.0015,.002,.0005]},
    "S004": {"name":"TAU","turb":"SA-neg","gl":3,"gs":13500000,
             "dCL":[.0005,.0003,-.0005,.0012,.0008,-.001],
             "dCD":[.00003,.00002,.00008,.00005,-.00005,.0001],
             "dCM":[.0003,.0002,-.0005,-.0003,.0008,-.0005]},
    "S005": {"name":"SU2","turb":"SA-neg","gl":3,"gs":11000000,
             "dCL":[-.0008,-.0005,.002,.0015,-.0005,.0012],
             "dCD":[.00015,.00012,.00005,-.00008,.0001,.0002],
             "dCM":[-.0002,.001,.0008,-.0005,-.001,.0015]},
    "S006": {"name":"FLUENT","turb":"RSM","gl":3,"gs":9500000,
             "dCL":[.008,.012,.02,.035,.055,.08],
             "dCD":[-.0005,-.0008,-.0012,-.002,-.0035,-.005],
             "dCM":[.003,.005,.008,.015,.02,.03]},
}

r = 2.0**(1.0/3.0)
rp = np.array([r**(2*k) for k in range(6)])

gc_specs = {
    "S001": {"gs":[64000000,32000000,16000000,8000000,4000000,2000000],
             "cl_fe":0.47,"cd_fe":0.0258,"cm_fe":-0.0405},
    "S002": {"gs":[51200000,25600000,12800000,6400000,3200000,1600000],
             "cl_fe":0.468,"cd_fe":0.02565,"cm_fe":-0.041},
    "S003": {"gs":[64800000,32400000,16200000,8100000,4050000,2025000],
             "cl_fe":0.4695,"cd_fe":0.02575,"cm_fe":-0.0398},
}

with h5py.File("/app/data/solver_results.h5","w") as f:
    f.attrs["description"]="DPW-8 multi-solver CFD results for NASA CRM WB"
    f.attrs["configuration"]="CRMWB"
    f.attrs["mach"]=0.85
    f.attrs["reynolds"]=5.0e6
    for sid,sd in solver_defs.items():
        g=f.create_group(sid)
        g.attrs["solver_name"]=sd["name"]
        g.attrs["turbulence_model"]=sd["turb"]
        g.attrs["grid_level"]=sd["gl"]
        g.attrs["grid_size"]=sd["gs"]
        p=g.create_group("polar")
        p.create_dataset("alpha",data=alphas)
        p.create_dataset("CL",data=CL_base+np.array(sd["dCL"]))
        p.create_dataset("CD",data=CD_base+np.array(sd["dCD"]))
        p.create_dataset("CM",data=CM_base+np.array(sd["dCM"]))
        if sid in gc_specs:
            gc=g.create_group("grid_convergence")
            sp=gc_specs[sid]
            gs=np.array(sp["gs"],dtype=np.float64)
            polar_cl = (CL_base+np.array(sd["dCL"]))[2]
            polar_cd = (CD_base+np.array(sd["dCD"]))[2]
            polar_cm = (CM_base+np.array(sd["dCM"]))[2]
            cl_ch2=(polar_cl-sp["cl_fe"])/rp[2]
            cd_ch2=(polar_cd-sp["cd_fe"])/rp[2]
            cm_ch2=(polar_cm-sp["cm_fe"])/rp[2]
            gc.attrs["alpha"]=2.0
            gc.create_dataset("grid_level",data=np.arange(1,7))
            gc.create_dataset("grid_size",data=gs)
            gc.create_dataset("CL",data=np.array([sp["cl_fe"]+cl_ch2*rp[k] for k in range(6)]))
            gc.create_dataset("CD",data=np.array([sp["cd_fe"]+cd_ch2*rp[k] for k in range(6)]))
            gc.create_dataset("CM",data=np.array([sp["cm_fe"]+cm_ch2*rp[k] for k in range(6)]))

with open("/app/data/experimental.csv","w") as f:
    f.write("# NASA CRM WBT0 Experimental Data\n")
    f.write("# Facility: NTF, Re_c=5.0e6, M=0.85\n")
    f.write("# Uncertainties are 95% confidence intervals\n")
    f.write("alpha,CL,CD,CM,CL_uncertainty,CD_uncertainty,CM_uncertainty\n")
    ecl=[0.178,0.32,0.467,0.608,0.687,0.731]
    ecd=[0.0188,0.0213,0.0259,0.0361,0.052,0.0685]
    ecm=[0.055,0.0045,-0.04,-0.0755,-0.06,-0.063]
    eu_cl=[0.003,0.003,0.003,0.004,0.005,0.006]
    eu_cd=[0.0003,0.0003,0.0003,0.0004,0.0005,0.0006]
    eu_cm=[0.002,0.002,0.002,0.003,0.003,0.004]
    for i in range(6):
        f.write(f"{alphas[i]:.1f},{ecl[i]:.4f},{ecd[i]:.4f},{ecm[i]:.4f},{eu_cl[i]:.4f},{eu_cd[i]:.4f},{eu_cm[i]:.4f}\n")

with open("/app/data/reference.toml","w") as f:
    f.write("""[configuration]
name = "CRMWB"
description = "Common Research Model Wing/Body"

[freestream]
mach = 0.85
reynolds = 5.0e6
temperature_R = 559.67

[reference]
area_sqin = 594720.0
chord_in = 275.80
span_in = 2313.50
semispan_in = 1156.75
xref_in = 1325.90
yref_in = 0.0
zref_in = 177.95
aspect_ratio = 9.0

[submission]
participant_id = "ENS"
submission_id = "01"
format = "tecplot_ascii"
columns = 31

[outlier_criteria]
confidence_level = 0.95
min_solvers_for_statistics = 3

[grid_convergence]
alpha_deg = 2.0
min_levels = 3
""")

print("Data generation complete.")
