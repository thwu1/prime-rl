# NONMEM-Style Event Record Specification

Records in a NONMEM-style dataset represent dosing events, observations, and system controls. Each row has an event ID (EVID) that determines how it is processed.

## Event Types

**EVID=0**: Observation. The DV column contains the measured dependent variable (concentration). Processed after all dosing events at the same time.

**EVID=1**: Dosing event. Deposits AMT into compartment CMT. If RATE is zero or absent, the dose is an instantaneous bolus. If RATE > 0, the dose is administered as a zero-order (constant-rate) infusion.

**EVID=3**: System reset. Sets all compartment amounts to zero and terminates any active infusions. Processed before any doses at the same time.

**EVID=4**: Reset-and-dose. Equivalent to EVID=3 immediately followed by EVID=1 at the same time.

## Dose Modifiers

These modifiers alter how a dose (EVID=1 or dose portion of EVID=4) is processed:

**RATE**: When > 0, the dose is infused at the specified constant rate. The infusion duration equals the effective amount divided by RATE.

**F1 (Bioavailability)**: Applies to CMT=1 doses only. When F1 > 0, the effective amount is AMT * F1. This scales both the deposited amount and, for infusions, the infusion duration. When F1 is zero or absent, the full AMT is used.

**ALAG1 (Absorption Lag Time)**: Applies to CMT=1 doses only. When ALAG1 > 0, the dose application is delayed by ALAG1 time units (dose is applied at TIME + ALAG1 instead of TIME).

## Repeated Dosing

**II (Inter-dose Interval)** and **ADDL (Additional Doses)**: When ADDL > 0 and II > 0, ADDL additional identical doses are scheduled at regular intervals of II after the (possibly lag-shifted) initial dose time. Each additional dose has the same properties (AMT, CMT, RATE, F1, ALAG1) as the original.

## Steady State

**SS=1** with **II > 0**: The system is advanced to pharmacokinetic steady state under the specified dosing regimen (dose with the given AMT, CMT, RATE, F1 at interval II) before the dose is applied. Steady state is the condition where compartment amounts no longer change meaningfully between successive dosing intervals.

## Processing Order at a Time Point

When multiple events share the same time:
1. Resets (EVID=3, or reset portion of EVID=4)
2. Doses (EVID=1, or dose portion of EVID=4, including steady-state advancement)
3. Observations (EVID=0)
