#!/usr/bin/env python3
"""Build and run the Henry saltwater intrusion model using MODFLOW 6 + FloPy."""

import json
from pprint import pformat

import flopy
import numpy as np

# Load parameters
with open("/app/parameters.json") as f:
    params = json.load(f)

# Extract parameters
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

# Compute grid dimensions
delr = lx / ncol
delc = 1.0
delv = lz / nlay
botm = [top_elev - (k + 1) * delv for k in range(nlay)]

# Model workspace
sim_ws = "/app/model"
sim_name = "henry"
gwfname = "gwf_henry"
gwtname = "gwt_henry"

# Build simulation
sim = flopy.mf6.MFSimulation(
    sim_name=sim_name, version="mf6", exe_name="mf6", sim_ws=sim_ws
)

# Time discretization
tdis_ds = ((perlen, nstp, 1.0),)
flopy.mf6.ModflowTdis(
    sim, time_units=time_units, nper=1, perioddata=tdis_ds
)

# ==================== GWF MODEL ====================
gwf = flopy.mf6.ModflowGwf(sim, modelname=gwfname)

# GWF iterative model solution
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

# Discretization
flopy.mf6.ModflowGwfdis(
    gwf,
    nlay=nlay, nrow=nrow, ncol=ncol,
    delr=delr, delc=delc,
    top=top_elev, botm=botm,
)

# Initial conditions (head = top of aquifer)
flopy.mf6.ModflowGwfic(gwf, strt=init_head)

# Node property flow (confined)
flopy.mf6.ModflowGwfnpf(
    gwf,
    save_specific_discharge=True,
    icelltype=0,
    k=hk,
)

# Buoyancy package (density-dependent flow)
buy_pd = [(0, drhodc, c_ref, gwtname, "none")]
flopy.mf6.ModflowGwfbuy(gwf, packagedata=buy_pd)

# Constant-head boundary (right side = seawater)
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

# Well boundary (left side = freshwater injection)
qwell = fw_inflow / nlay
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

# Output control
flopy.mf6.ModflowGwfoc(
    gwf,
    budget_filerecord=f"{gwfname}.cbc",
    head_filerecord=f"{gwfname}.hds",
    headprintrecord=[("COLUMNS", 10, "WIDTH", 15, "DIGITS", 6, "GENERAL")],
    saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
    printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")],
)

# ==================== GWT MODEL ====================
gwt = flopy.mf6.ModflowGwt(sim, modelname=gwtname)

# GWT iterative model solution
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
sim.register_ims_package(imsgwt, [gwt.name])

# Discretization
flopy.mf6.ModflowGwtdis(
    gwt,
    nlay=nlay, nrow=nrow, ncol=ncol,
    delr=delr, delc=delc,
    top=top_elev, botm=botm,
)

# Initial conditions (fully saline)
flopy.mf6.ModflowGwtic(
    gwt, strt=init_conc, filename=f"{gwtname}.ic"
)

# Advection (upstream scheme)
flopy.mf6.ModflowGwtadv(
    gwt, scheme="UPSTREAM", filename=f"{gwtname}.adv"
)

# Dispersion (molecular diffusion only)
flopy.mf6.ModflowGwtdsp(
    gwt,
    xt3d_off=True,
    diffc=diffc,
    filename=f"{gwtname}.dsp",
)

# Mass storage and transfer (porosity)
flopy.mf6.ModflowGwtmst(
    gwt, porosity=porosity, filename=f"{gwtname}.sto"
)

# Source-sink mixing (link CHD and WEL concentrations to transport)
sourcerecarray = [
    ("CHD-1", "AUX", "CONCENTRATION"),
    ("WEL-1", "AUX", "CONCENTRATION"),
]
flopy.mf6.ModflowGwtssm(
    gwt, sources=sourcerecarray, filename=f"{gwtname}.ssm"
)

# Output control
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

# ==================== GWF-GWT EXCHANGE ====================
flopy.mf6.ModflowGwfgwt(
    sim,
    exgtype="GWF6-GWT6",
    exgmnamea=gwfname,
    exgmnameb=gwtname,
    filename=f"{sim_name}.gwfgwt",
)

# ==================== WRITE AND RUN ====================
print("Writing simulation files...")
sim.write_simulation()

print("Running simulation...")
success, buff = sim.run_simulation(report=True)
assert success, f"Simulation failed:\n{pformat(buff)}"

print("Simulation completed successfully.")
