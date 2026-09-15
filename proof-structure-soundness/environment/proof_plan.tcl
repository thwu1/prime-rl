# ========================================================================
# JasperGold Proof Structure Plan — Exported Configuration
# Design: soc_top  |  Tool: JasperGold v21.12  |  Date: 2024-11-15
# ========================================================================
#
# Configuration format reference:
#   proof_node <id> -strategy <strat> [-parent <pid>] [-desc "<text>"] [-status <s>]
#   guarantee <node_id> <property_name>
#   assume <node_id> <ref_node>:<ref_guarantee>
#   split_config <node_id> -signal <sig> -constraint <smt2_file>
#   partition_config <node_id> -signal <sig>
#   partition_value <child_id> <value>
#   stopat_config <node_id> -signals {<sig_list>}
#
# Strategies: assume_guarantee, case_split, partition, stopat, leaf
# ========================================================================

# --- Root ---
proof_node P0 -strategy assume_guarantee -desc "Top-level SoC design correctness"

# --- Memory Subsystem (case-split on access_type) ---
proof_node P1 -strategy case_split -parent P0 -desc "Memory subsystem data integrity"
guarantee P1 mem_data_integrity
assume P1 P2:arb_grant_fairness
split_config P1 -signal access_type -constraint /app/constraints/access_type.smt2

proof_node P1a -strategy leaf -parent P1 -desc "Read path correctness" -status proven
proof_node P1b -strategy leaf -parent P1 -desc "Write path correctness" -status proven

# --- Bus Arbiter (partition on bus_ids) ---
proof_node P2 -strategy partition -parent P0 -desc "Bus arbiter fairness and correctness"
guarantee P2 arb_grant_fairness
assume P2 P3:dma_transfer_complete
partition_config P2 -signal bus_ids

proof_node P2a -strategy leaf -parent P2 -desc "Bus 0 arbitration" -status proven
partition_value P2a 0
proof_node P2b -strategy leaf -parent P2 -desc "Bus 1 arbitration" -status proven
partition_value P2b 1
proof_node P2c -strategy leaf -parent P2 -desc "Bus 2 arbitration" -status proven
partition_value P2c 2

# --- DMA Engine (case-split on dma_mode) ---
proof_node P3 -strategy case_split -parent P0 -desc "DMA engine transfer correctness"
guarantee P3 dma_transfer_complete
assume P3 P1:mem_data_integrity
split_config P3 -signal dma_mode -constraint /app/constraints/dma_mode.smt2

proof_node P3a -strategy leaf -parent P3 -desc "Scatter mode correctness" -status proven
proof_node P3b -strategy leaf -parent P3 -desc "Gather mode correctness" -status proven

# --- Interrupt Controller (nested assume-guarantee) ---
proof_node P4 -strategy assume_guarantee -parent P0 -desc "Interrupt controller correctness"
guarantee P4 irq_delivery_guaranteed

proof_node P4a -strategy leaf -parent P4 -desc "Priority encoder ordering" -status proven
guarantee P4a priority_correct
assume P4a P4b:mask_applied_correctly

proof_node P4b -strategy leaf -parent P4 -desc "Interrupt mask register" -status proven
guarantee P4b mask_applied_correctly
assume P4b P4a:priority_correct

# --- Clock Domain Crossing (stopat) ---
proof_node P5 -strategy stopat -parent P0 -desc "Clock domain crossing safety"
guarantee P5 cdc_no_metastability
stopat_config P5 -signals {sync_stage1 sync_stage2}

proof_node P5a -strategy leaf -parent P5 -desc "CDC handshake protocol compliance" -status proven

# --- Power Management (case-split on power_state) ---
proof_node P6 -strategy case_split -parent P0 -desc "Power management unit correctness"
guarantee P6 power_transitions_safe
split_config P6 -signal power_state -constraint /app/constraints/power_state.smt2

proof_node P6a -strategy leaf -parent P6 -desc "Active state correctness" -status proven
proof_node P6b -strategy leaf -parent P6 -desc "Idle state correctness" -status proven
proof_node P6c -strategy leaf -parent P6 -desc "Sleep state correctness" -status proven
proof_node P6d -strategy leaf -parent P6 -desc "Deep sleep state correctness" -status proven

# --- Error Handling (case-split on error_class) ---
proof_node P7 -strategy case_split -parent P0 -desc "Error handling subsystem"
guarantee P7 errors_handled_correctly
assume P7 P8:watchdog_reset_correct
split_config P7 -signal error_class -constraint /app/constraints/error_class.smt2

proof_node P7a -strategy leaf -parent P7 -desc "Correctable error handling" -status proven
proof_node P7b -strategy leaf -parent P7 -desc "Uncorrectable error handling" -status proven

# --- Watchdog Timer (assume-guarantee) ---
proof_node P8 -strategy assume_guarantee -parent P0 -desc "Watchdog timer and reset controller"
guarantee P8 watchdog_reset_correct
assume P8 P7:errors_handled_correctly

proof_node P8a -strategy leaf -parent P8 -desc "Watchdog countdown logic" -status proven
guarantee P8a countdown_accurate

proof_node P8b -strategy leaf -parent P8 -desc "Reset sequence controller" -status proven
guarantee P8b reset_sequence_valid
assume P8b P8a:countdown_accurate
