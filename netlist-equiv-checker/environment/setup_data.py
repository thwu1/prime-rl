#!/usr/bin/env python3
"""Generate ISPD 2026 evaluation pipeline data."""

import os
import json
import math

def mkdirs(p):
    os.makedirs(p, exist_ok=True)

def write(p, c):
    with open(p, "w") as f:
        f.write(c)

# ================================================================
# Metric definitions
# Fields: tns, wns, total_power_w, leakage_w, slew_over_sum, cap_over_sum,
#         fanout_over_sum, tool_runtime, flow_runtime, placement_legal,
#         max_gr_overflow, total_gr_overflow, avg_displacement, total_insts
# ================================================================
METRICS = {
    "baseline": {
        "aes_cipher_top": (-1500.0, -5.0, 0.058, 0.008, 2.0, 0.5, 10.0, 120, 300, 1, 2.0, 6.0, 5.0, 25432),
        "jpeg_encoder":   (-2000.0, -8.0, 0.092, 0.012, 5.0, 1.0, 20.0, 180, 450, 1, 3.0, 10.0, 8.0, 40128),
    },
    "team_alpha": {
        "aes_cipher_top": (-800.0, -2.5, 0.052, 0.007, 1.0, 0.3, 5.0, 150, 350, 1, 1.5, 4.0, 6.0, 25450),
        "jpeg_encoder":   (-1200.0, -4.0, 0.0825, 0.0105, 3.0, 0.7, 12.0, 220, 500, 1, 2.0, 7.0, 9.0, 40145),
    },
    "team_beta": {
        "aes_cipher_top": (-1100.0, -3.5, 0.0435, 0.0055, 1.5, 0.4, 8.0, 100, 280, 1, 1.8, 5.0, 4.0, 25445),
        "jpeg_encoder":   (-1500.0, -6.0, 0.068, 0.008, 4.0, 0.8, 15.0, 150, 400, 1, 2.5, 8.0, 7.0, 40140),
    },
    "team_gamma": {
        "aes_cipher_top": (-900.0, -3.0, 0.0485, 0.0065, 1.2, 0.35, 7.0, 130, 320, 0, 1.6, 4.5, 5.5, 25440),
        "jpeg_encoder":   (-1400.0, -5.0, 0.0775, 0.0095, 3.5, 0.65, 14.0, 200, 480, 1, 2.8, 9.0, 8.5, 40135),
    },
    "team_delta": {
        "aes_cipher_top": (-1300.0, -4.0, 0.0555, 0.0075, 1.8, 0.45, 9.0, 160, 380, 1, 2.0, 6.0, 7.0, 25438),
        "jpeg_encoder":   (-1700.0, -6.5, 0.086, 0.011, 4.5, 0.9, 18.0, 250, 520, 1, 4.0, 13.0, 10.0, 40130),
    },
}

DESIGNS = ["aes_cipher_top", "jpeg_encoder"]
TEAMS = ["team_alpha", "team_beta", "team_gamma", "team_delta"]

# ================================================================
# Log generation helpers
# ================================================================

def gen_gr_grid(max_over, total_over):
    """Generate 3x3 GR congestion grid data."""
    cap = 100
    remaining = total_over - max_over
    per_cell = remaining / 8.0 if remaining > 0 else 0.0
    lines = []
    for x in range(3):
        for y in range(3):
            if x == 0 and y == 0:
                use = cap + max_over
            elif per_cell > 0:
                use = cap + per_cell
            else:
                use = cap * 0.8
            cong = (use / cap) * 100.0
            lines.append(f"{x} {y} {cap} {use:.6f} {cong:.6f}")
    return "\n".join(lines)


def gen_violation_entries(target_sum, vtype):
    """Generate ERC violation table entries summing to target_sum."""
    if target_sum <= 0:
        return ""
    if target_sum < 1.0:
        n = 1
    elif target_sum < 5.0:
        n = 2
    else:
        n = 4
    per_entry = target_sum / n
    lines = []
    if vtype == "slew":
        limit = 0.100000
        for i in range(n):
            val = limit + per_entry
            slack = -(val - limit)
            lines.append(f"net_{i}/g{i}/Y                          {limit:.6f}   {val:.6f}  {slack:.6f} (VIOLATED)")
    elif vtype == "cap":
        limit = 0.050000
        for i in range(n):
            val = limit + per_entry
            slack = -(val - limit)
            lines.append(f"net_{i}/g{i}/Y                          {limit:.6f}   {val:.6f}  {slack:.6f} (VIOLATED)")
    elif vtype == "fanout":
        limit = 10.0
        for i in range(n):
            val = limit + per_entry
            slack = -(val - limit)
            lines.append(f"net_{i}/g{i}/Y                          {limit:.6f}   {val:.6f}  {slack:.6f} (VIOLATED)")
    return "\n".join(lines)


def gen_log(design_name, m):
    """Generate a realistic OpenROAD evaluation log from metric tuple."""
    tns, wns, tp_w, lk_w, slew, cap, fanout, trt, frt, legal, max_o, tot_o, disp, ninst = m
    dyn_w = tp_w - lk_w
    int_w = dyn_w * 0.45
    sw_w = dyn_w * 0.55

    if legal:
        legal_block = "Placement is legal; skip legalization."
    else:
        legal_block = ("Placement NOT legal; running detailed_placement...\n"
                       "WARN: Placement still illegal after detailed_placement.")

    grid = gen_gr_grid(max_o, tot_o)
    slew_ent = gen_violation_entries(slew, "slew")
    cap_ent = gen_violation_entries(cap, "cap")
    fanout_ent = gen_violation_entries(fanout, "fanout")

    log = f"""[INFO ODB-0128] Design: {design_name}
[INFO ODB-0131] Number of components: {ninst}
[INFO ODB-0133] Number of nets: {ninst // 2}

### Check placement legality ###
{legal_block}

### Global routing (first attempt) ###
[INFO GRT-0001] Running global routing...
[INFO GRT-0018] Global routing completed.

===== METRICS =====
design:                 {design_name}
placement_legal:        {legal}
total_insts:            {ninst}

time 1ns
capacitance 1pF
power 1mW

wns max {wns:.3f}

tns max {tns:.3f}

--------------------------------------------------------------------------
Group                   Coverage      Coverage      Wns            Tns
--------------------------------------------------------------------------
Reg2Clk                  100.00        100.00      {wns:.3f}       {tns * 0.6:.3f}
Reg2Reg                  100.00        100.00      {wns * 0.8:.3f}  {tns * 0.3:.3f}
In2Reg                   100.00        100.00      {wns * 0.5:.3f}  {tns * 0.1:.3f}
--------------------------------------------------------------------------

Power (Watts)
                  Internal  Switching    Leakage      Total
-----------  ----------  ----------  ----------  ----------
Sequential      {int_w*0.30:.3e}  {sw_w*0.30:.3e}  {lk_w*0.40:.3e}  {(int_w*0.30+sw_w*0.30+lk_w*0.40):.3e}
Combinational   {int_w*0.50:.3e}  {sw_w*0.50:.3e}  {lk_w*0.35:.3e}  {(int_w*0.50+sw_w*0.50+lk_w*0.35):.3e}
Macro           {int_w*0.20:.3e}  {sw_w*0.20:.3e}  {lk_w*0.25:.3e}  {(int_w*0.20+sw_w*0.20+lk_w*0.25):.3e}
Total           {int_w:.3e}  {sw_w:.3e}  {lk_w:.3e}  {tp_w:.3e}

Start Global Routing Results Analysis ...
{grid}
End Global Routing Results Analysis ...

max slew

Pin                                    Limit      Value      Slack
-----------------------------------------------------------------------
{slew_ent}

max capacitance

Pin                                    Limit      Value      Slack
-----------------------------------------------------------------------
{cap_ent}

max fanout

Pin                                    Limit      Value      Slack
-----------------------------------------------------------------------
{fanout_ent}

avg_displacement:       {disp:.6f}

[INFO] OR RSZ running time: {trt} second
[INFO] Flow running time: {frt} second
"""
    return log


# ================================================================
# Netlist definitions
# ================================================================

AES_PRE_NODES = """\
name,master,type,x,y
g0,NAND2x1_ASAP7_75t_L,Inst,100.0,200.0
g1,NOR2x1_ASAP7_75t_L,Inst,300.0,200.0
g2,AND2x2_ASAP7_75t_L,Inst,500.0,200.0
tap0,TAPCELL_ASAP7,Inst,50.0,100.0
m0,sram_asap7_64x256_1rw,Macro,800.0,800.0
io_a,PAD,IO,0.0,0.0
io_b,PAD,IO,0.0,500.0
io_z,PAD,IO,1000.0,250.0
"""

AES_PRE_NETS = """\
n0,io_a _IO_,g0 A1
n1,io_b _IO_,g0 A2
n2,g0 Y,g1 A1,g2 A1
n3,g1 Y,io_z _IO_
n4,g2 Y,m0 A
"""

AES_POST_VALID_NODES = """\
name,master,type,x,y
g0,NAND2x2_ASAP7_75t_L,Inst,100.0,200.0
g1,NOR2x1_ASAP7_75t_L,Inst,300.0,200.0
g2,AND2x2_ASAP7_75t_L,Inst,500.0,200.0
buf0,BUFx2_ASAP7_75t_L,Inst,200.0,200.0
tap0,TAPCELL_ASAP7,Inst,50.0,100.0
m0,sram_asap7_64x256_1rw,Macro,800.0,800.0
io_a,PAD,IO,0.0,0.0
io_b,PAD,IO,0.0,500.0
io_z,PAD,IO,1000.0,250.0
"""

AES_POST_VALID_NETS = """\
n0,io_a _IO_,g0 A1
n1,io_b _IO_,g0 A2
n2a,g0 Y,buf0 A
n2b,buf0 Y,g1 A1,g2 A1
n3,g1 Y,io_z _IO_
n4,g2 Y,m0 A
"""

JPEG_PRE_NODES = """\
name,master,type,x,y
g0,OR2x2_ASAP7_75t_L,Inst,100.0,200.0
g1,NAND2x1_ASAP7_75t_L,Inst,300.0,200.0
g2,XOR2x1_ASAP7_75t_L,Inst,500.0,200.0
g3,AOI21x1_ASAP7_75t_L,Inst,700.0,200.0
tap0,TAPCELL_ASAP7,Inst,50.0,100.0
m0,sram_asap7_64x256_1rw,Macro,800.0,800.0
io_a,PAD,IO,0.0,0.0
io_b,PAD,IO,0.0,500.0
io_c,PAD,IO,500.0,0.0
io_z,PAD,IO,1000.0,250.0
"""

JPEG_PRE_NETS = """\
n0,io_a _IO_,g0 A1
n1,io_b _IO_,g0 A2,g1 A2
n2,io_c _IO_,g2 A
n3,g0 Y,g1 A1
n4,g1 Y,g3 A1
n5,g2 Y,g3 A2
n6,g3 Y,io_z _IO_
"""

JPEG_POST_VALID_NODES = """\
name,master,type,x,y
g0,OR2x2_ASAP7_75t_L,Inst,100.0,200.0
g1,NAND2x2_ASAP7_75t_L,Inst,300.0,200.0
g2,XOR2x1_ASAP7_75t_L,Inst,500.0,200.0
g3,AOI21x1_ASAP7_75t_L,Inst,700.0,200.0
buf0,BUFx2_ASAP7_75t_L,Inst,400.0,200.0
tap0,TAPCELL_ASAP7,Inst,50.0,100.0
m0,sram_asap7_64x256_1rw,Macro,800.0,800.0
io_a,PAD,IO,0.0,0.0
io_b,PAD,IO,0.0,500.0
io_c,PAD,IO,500.0,0.0
io_z,PAD,IO,1000.0,250.0
"""

JPEG_POST_VALID_NETS = """\
n0,io_a _IO_,g0 A1
n1,io_b _IO_,g0 A2,g1 A2
n2,io_c _IO_,g2 A
n3,g0 Y,g1 A1
n4a,g1 Y,buf0 A
n4b,buf0 Y,g3 A1
n5,g2 Y,g3 A2
n6,g3 Y,io_z _IO_
"""

# team_beta jpeg: invalid cell substitution (OR2 -> AO21, different equiv group)
JPEG_POST_BETA_NODES = """\
name,master,type,x,y
g0,AO21x1_ASAP7_75t_L,Inst,100.0,200.0
g1,NAND2x2_ASAP7_75t_L,Inst,300.0,200.0
g2,XOR2x1_ASAP7_75t_L,Inst,500.0,200.0
g3,AOI21x1_ASAP7_75t_L,Inst,700.0,200.0
buf0,BUFx2_ASAP7_75t_L,Inst,400.0,200.0
tap0,TAPCELL_ASAP7,Inst,50.0,100.0
m0,sram_asap7_64x256_1rw,Macro,800.0,800.0
io_a,PAD,IO,0.0,0.0
io_b,PAD,IO,0.0,500.0
io_c,PAD,IO,500.0,0.0
io_z,PAD,IO,1000.0,250.0
"""

JPEG_POST_BETA_NETS = JPEG_POST_VALID_NETS

# ================================================================
# Scoring documentation
# ================================================================

SCORING_DOC = """\
ISPD 2026 Post-Placement Buffering and Sizing Contest
=====================================================
Evaluation Metrics and Scoring Methodology
(Extracted from the contest paper, Section 4.2)

1. OVERVIEW

Contestants' solutions are evaluated based on global routing quality,
runtime efficiency and legality, using OpenROAD's timing and power
analysis infrastructure. The scoring metric compares normalized
improvement versus a baseline (OpenROAD Resizer with repair_design
and repair_timing commands).

Metric weights are specified in /app/data/scoring_weights.json.


2. HARD CONSTRAINTS

The following constraints must be satisfied by all submitted solutions.
Violation of ANY hard constraint results in a Design Score of 0 for
that design.

  - Placement legality: Final placement must pass legality checks
    performed by the OpenROAD checkPlacement command.

  - Logical equivalence: The post-optimization netlist must be
    logically equivalent to the pre-optimization netlist. This
    includes sizing equivalence (substituted cells must be
    functionally equivalent), instance insertion rules (only buffers
    and inverters may be inserted), pin connectivity preservation,
    and buffer tree parity (even number of inverters on each
    source-to-sink path).


3. PPA METRICS

The primary PPA (power, performance, area) metrics are calculated as
normalized improvements over the baseline:

  S_tns    = (|TNS_baseline| - |TNS_contestant|) / |TNS_baseline|
  S_dpower = (DPower_baseline - DPower_contestant) / DPower_baseline
  S_lpower = (LPower_baseline - LPower_contestant) / LPower_baseline

where:
  - TNS is total negative slack (reported by OpenSTA)
  - DPower is dynamic power (total power minus leakage power)
  - LPower is leakage power

  PPA_score = w_tns * S_tns + w_dpower * S_dpower + w_lpower * S_lpower


4. ERC VIOLATION PENALTY

ERC violations are penalized based on the sum of violation values
after global routing, normalized by baseline violation values:

  P_erc = w_slew * (SlewViol_contestant / SlewViol_baseline)
        + w_cap  * (CapViol_contestant  / CapViol_baseline)
        + w_fanout * (FanoutViol_contestant / FanoutViol_baseline)

where SlewViol, CapViol, FanoutViol are the sums of individual
violation amounts (value - limit) for each violated pin.


5. RUNTIME PENALTY

Runtime efficiency is evaluated using both the buffering and sizing
tool runtime and the total flow runtime:

  P_tool = max(0, (ToolRuntime_contestant - ToolRuntime_baseline) / ToolRuntime_baseline)
  P_flow = max(0, (FlowRuntime_contestant - FlowRuntime_baseline) / FlowRuntime_baseline)
  P_runtime = w_tool_runtime * P_tool + w_flow_runtime * P_flow

A maximum runtime limit is enforced for each test case.


6. DISPLACEMENT PENALTY

Placement quality is evaluated using the average Manhattan displacement
of movable cells from their original positions:

  P_displacement = w_displacement * max(0, (AvgDisp_contestant - AvgDisp_baseline) / AvgDisp_baseline)


7. GLOBAL ROUTING OVERFLOW PENALTY

Poor global routing quality is penalized using routing overflow metrics:

  P_max_overflow = max(0, (MaxOverflow_contestant - MaxOverflow_baseline) / MaxOverflow_baseline)
  P_total_overflow = max(0, (TotalOverflow_contestant - TotalOverflow_baseline) / TotalOverflow_baseline)
  P_overflow = w_max_overflow * P_max_overflow + w_total_overflow * P_total_overflow


8. DESIGN SCORE

The Design Score for a single design is:

  DesignScore = PPA_score - P_erc - P_runtime - P_displacement - P_overflow

if all hard constraints are satisfied; otherwise DesignScore = 0.


9. FINAL SCORE

The final score (total score) is the sum of Design Scores across all
evaluated designs:

  FinalScore = sum(DesignScore_i for each design i)
"""

SCORING_WEIGHTS = {
    "w_tns": 80,
    "w_dpower": 40,
    "w_lpower": 40,
    "w_slew": 0.001,
    "w_cap": 10,
    "w_fanout": 1,
    "w_tool_runtime": 1,
    "w_flow_runtime": 1,
    "w_displacement": 1,
    "w_max_overflow": 1,
    "w_total_overflow": 1
}


# ================================================================
# Main generation
# ================================================================

def main():
    # Create directory structure
    for d in [
        "/app/logs/baseline",
        "/app/logs/submissions",
        "/app/netlists/pre_opt",
        "/app/tools",
        "/app/data",
        "/app/docs",
    ]:
        mkdirs(d)
    for team in TEAMS:
        mkdirs(f"/app/logs/submissions/{team}")
        for design in DESIGNS:
            mkdirs(f"/app/netlists/submissions/{team}/{design}")
    for design in DESIGNS:
        mkdirs(f"/app/netlists/pre_opt/{design}")

    # Write scoring docs
    write("/app/docs/ispd26_scoring.txt", SCORING_DOC)

    # Write scoring weights
    write("/app/data/scoring_weights.json", json.dumps(SCORING_WEIGHTS, indent=2) + "\n")

    # Write baseline logs
    for design in DESIGNS:
        log = gen_log(design, METRICS["baseline"][design])
        write(f"/app/logs/baseline/{design}.log", log)

    # Write team submission logs
    for team in TEAMS:
        for design in DESIGNS:
            log = gen_log(design, METRICS[team][design])
            write(f"/app/logs/submissions/{team}/{design}.log", log)

    # Write pre-opt netlists
    write("/app/netlists/pre_opt/aes_cipher_top/node.csv", AES_PRE_NODES)
    write("/app/netlists/pre_opt/aes_cipher_top/nets.csv", AES_PRE_NETS)
    write("/app/netlists/pre_opt/jpeg_encoder/node.csv", JPEG_PRE_NODES)
    write("/app/netlists/pre_opt/jpeg_encoder/nets.csv", JPEG_PRE_NETS)

    # Write post-opt netlists for submissions
    for team in TEAMS:
        # aes_cipher_top: all teams have valid optimization
        write(f"/app/netlists/submissions/{team}/aes_cipher_top/node.csv", AES_POST_VALID_NODES)
        write(f"/app/netlists/submissions/{team}/aes_cipher_top/nets.csv", AES_POST_VALID_NETS)

        # jpeg_encoder: team_beta has invalid cell substitution
        if team == "team_beta":
            write(f"/app/netlists/submissions/{team}/jpeg_encoder/node.csv", JPEG_POST_BETA_NODES)
            write(f"/app/netlists/submissions/{team}/jpeg_encoder/nets.csv", JPEG_POST_BETA_NETS)
        else:
            write(f"/app/netlists/submissions/{team}/jpeg_encoder/node.csv", JPEG_POST_VALID_NODES)
            write(f"/app/netlists/submissions/{team}/jpeg_encoder/nets.csv", JPEG_POST_VALID_NETS)

    print("All evaluation data generated successfully.")


if __name__ == "__main__":
    main()
