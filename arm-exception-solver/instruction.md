Binary dump files in `/app/scs_dumps/` contain ARM Cortex-M processor exception state snapshots in CMEX v1 format. Each file holds multiple state records encoding System Control Block registers, NVIC state, active/pending exceptions, and a diagnostic query.

Format specification: `/app/format_spec.txt`. A C parsing utility at `/app/tools/` (buildable via `make`) can decode dump contents but may contain defects — cross-check against raw binary data.

For each dump file `/app/scs_dumps/<name>.bin`, produce `/app/results/<name>.json` mapping each record identifier to the computed query result. Exception model behavior must conform to the ARMv7-M Architecture Reference Manual (DDI 0403E). ARMv6-M records follow the simplified exception model for that variant.

SHPR1/SHPR2/SHPR3 registers encode configured priorities for system exception handlers. NVIC_IPR bytes encode external interrupt priorities. Both are needed when evaluating exception preemption against the current execution priority level.