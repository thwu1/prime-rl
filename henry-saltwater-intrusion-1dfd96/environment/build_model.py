#!/usr/bin/env python3
"""Build and run a coupled GWF-GWT simulation for the Henry problem."""

import json
import sys

import flopy
import numpy as np

with open("/app/parameters.json") as f:
    params = json.load(f)

lx = params["aquifer"]["length_x"]
lz = params["aquifer"]["length_z"]
hk = params["aquifer"]["hydraulic_conductivity"]
porosity = params["aquifer"]["porosity"]
top_elev = params["aquifer"]["top_elevation"]

sw_conc = params["seawater"]["concentration"]
sw_head = params["seawater"]["boundary_head"]

fw_conc = params["freshwater"]["concentration"]
fw_inflow = params["freshwater"]["total_inflow_rate"]

diffc = params["transport"]["molecular_diffusion_coefficient"]
init_conc = params["transport"]["initial_concentration"]

rho_fw = params["density"]["freshwater_density"]
rho_sw = params["density"]["seawater_density"]
c_ref = params["density"]["reference_concentration"]
drhodc = params["density"]["density_slope"]

nlay = params["discretization"]["nlay"]
nrow = params["discretization"]["nrow"]
ncol = params["discretization"]["ncol"]

perlen = params["simulation"]["period_length_days"]
nstp = params["simulation"]["num_time_steps"]
time_units = params["simulation"]["time_units"].upper()
init_head = params["simulation"]["initial_head"]

nouter = params["solver"]["outer_maximum"]
ninner = params["solver"]["inner_maximum"]
hclose = params["solver"]["head_change_tolerance"]
rclose = params["solver"]["residual_tolerance"]
relax = params["solver"]["relaxation_factor"]

delr = lx / ncol
delc = 1.0
delv = lz / nlay
botm = [top_elev - (k + 1) * delv for k in range(nlay)]

sim_ws = "/app/model"
sim_name = "henry"
gwfname = "gwf_henry"
gwtname = "gwt_henry"

sim = flopy.mf6.MFSimulation(
    sim_name=sim_name, version="mf6", exe_name="mf6", sim_ws=sim_ws
)

tdis_ds = ((perlen, nstp, 1.0),)
flopy.mf6.ModflowTdis(
    sim, time_units=time_units, nper=1, perioddata=tdis_ds
)

# ---- Groundwater Flow Model ----
gwf = flopy.mf6.ModflowGwf(sim, modelname=gwfname)

imsgwf = flopy.mf6.ModflowIms(
    sim,
    print_option="ALL",
    outer_dvclose=hclose,
    outer_maximum=nouter,
    under_relaxation="NONE",
    inner_maximum=ninner,
    inner_dvclose=hclose,
    rcloserecord=rclose,
    linear_acceleration="BICGSTAB",
    scaling_method="NONE",
    reordering_method="NONE",
    relaxation_factor=relax,
    filename=f"{gwfname}.ims",
)
sim.register_ims_package(imsgwf, [gwfname])

flopy.mf6.ModflowGwfdis(
    gwf,
    nlay=nlay, nrow=nrow, ncol=ncol,
    delr=delr, delc=delc,
    top=top_elev, botm=botm,
)

flopy.mf6.ModflowGwfic(gwf, strt=init_head)

flopy.mf6.ModflowGwfnpf(
    gwf,
    save_specific_discharge=True,
    icelltype=0,
    k=hk,
)

buy_pd = [(0, drhodc, c_ref, "transport", "none")]
flopy.mf6.ModflowGwfbuy(gwf, packagedata=buy_pd)

chdspd = [[(k, 0, ncol - 1), sw_head, sw_conc] for k in range(nlay)]
flopy.mf6.ModflowGwfchd(
    gwf,
    stress_period_data=chdspd,
    print_input=True,
    print_flows=True,
    save_flows=False,
    pname="CHD-1",
    auxiliary="CONCENTRATION",
    filename=f"{gwfname}.chd",
)

qwell = -fw_inflow / nlay
welspd = [[(k, 0, 0), qwell, fw_conc] for k in range(nlay)]
flopy.mf6.ModflowGwfwel(
    gwf,
    stress_period_data=welspd,
    print_input=True,
    print_flows=True,
    save_flows=False,
    pname="WEL-1",
    auxiliary="CONCENTRATION",
    filename=f"{gwfname}.wel",
)

flopy.mf6.ModflowGwfoc(
    gwf,
    budget_filerecord=f"{gwfname}.cbc",
    head_filerecord=f"{gwfname}.hds",
    headprintrecord=[("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")],
    saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
)

# ---- Groundwater Transport Model ----
gwt = flopy.mf6.ModflowGwt(sim, modelname=gwtname)

imsgwt = flopy.mf6.ModflowIms(
    sim,
    print_option="ALL",
    outer_dvclose=hclose,
    outer_maximum=nouter,
    under_relaxation="NONE",
    inner_maximum=ninner,
    inner_dvclose=hclose,
    rcloserecord=rclose,
    linear_acceleration="BICGSTAB",
    scaling_method="NONE",
    reordering_method="NONE",
    relaxation_factor=relax,
    filename=f"{gwtname}.ims",
)
sim.register_ims_package(imsgwt, [gwfname])

flopy.mf6.ModflowGwtdis(
    gwt,
    nlay=nlay, nrow=nrow, ncol=ncol,
    delr=delr, delc=delc,
    top=top_elev, botm=botm,
)

flopy.mf6.ModflowGwtic(
    gwt, strt=init_conc, filename=f"{gwtname}.ic"
)

flopy.mf6.ModflowGwtadv(
    gwt, scheme="UPSTREAM", filename=f"{gwtname}.adv"
)

flopy.mf6.ModflowGwtdsp(
    gwt,
    xt3d_off=True,
    diffc=diffc,
    filename=f"{gwtname}.dsp",
)

flopy.mf6.ModflowGwtmst(
    gwt, porosity=porosity, filename=f"{gwtname}.sto"
)

sourcerecarray = [
    ("CHD", "AUX", "CONCENTRATION"),
    ("WEL", "AUX", "CONCENTRATION"),
]
flopy.mf6.ModflowGwtssm(
    gwt, sources=sourcerecarray, filename=f"{gwtname}.ssm"
)

flopy.mf6.ModflowGwtoc(
    gwt,
    budget_filerecord=f"{gwtname}.cbc",
    concentration_filerecord=f"{gwtname}.ucn",
    concentrationprintrecord=[
        ("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")
    ],
    saverecord=[("CONCENTRATION", "ALL")],
    printrecord=[("CONCENTRATION", "LAST"), ("BUDGET", "LAST")],
)

print("Writing simulation files...")
sim.write_simulation()

print("Running simulation...")
success, buff = sim.run_simulation(report=True)
if not success:
    print("Simulation failed!")
    sys.exit(1)

print("Simulation completed successfully.")
