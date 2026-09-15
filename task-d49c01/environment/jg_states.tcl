#!/usr/bin/env tclsh
# JasperGold Proof Structure App - Design State Configuration
# Generated from formal model elaboration (v21.12)
#
# This file uses TCL namespaces, procedures, and conditional feature flags
# to compute design state enumerations. It must be evaluated with tclsh
# to resolve the final set of valid enumeration values.

namespace eval ::jg {
    variable states
    variable flags

    array set flags {
        HAS_MULTIPLY    1
        HAS_DIVIDE      1
        HAS_FPU         0
        EXTENDED_CACHE  1
    }
}

proc ::jg::register_state {path values} {
    variable states
    set states($path) $values
}

proc ::jg::append_state {path extras} {
    variable states
    if {![info exists states($path)]} {
        error "State '$path' not yet registered"
    }
    foreach v $extras {
        lappend states($path) $v
    }
}

proc ::jg::flag {name} {
    variable flags
    if {[info exists flags($name)]} {
        return $flags($name)
    }
    return 0
}

# --- Cache controller FSM ---
::jg::register_state cache_ctrl.state {IDLE LOOKUP WRITEBACK FILL}
if {[::jg::flag EXTENDED_CACHE]} {
    ::jg::append_state cache_ctrl.state {REFILL}
}

# --- ALU operations (feature-gated) ---
::jg::register_state alu.alu_op {ADD SUB AND OR XOR SHL SHR SRA}
if {[::jg::flag HAS_MULTIPLY]} {
    ::jg::append_state alu.alu_op {MUL}
}
if {[::jg::flag HAS_DIVIDE]} {
    ::jg::append_state alu.alu_op {DIV}
}

# --- Simple state enumerations ---
::jg::register_state mem_arbiter.priority {CACHE DMA}
::jg::register_state dma_engine.dma_state {IDLE SETUP ACTIVE DONE}
::jg::register_state bus_bridge.bridge_state {IDLE REQUEST TRANSFER COMPLETE}

# --- Export resolved states as JSON ---
proc ::jg::export_json {outpath} {
    variable states
    set names [lsort [array names states]]
    set lines [list]
    foreach name $names {
        set vals [list]
        foreach v $states($name) {
            lappend vals "\"$v\""
        }
        lappend lines "  \"$name\": \[[join $vals ", "]\]"
    }
    set fd [open $outpath w]
    puts $fd "\{"
    puts $fd [join $lines ",\n"]
    puts $fd "\}"
    close $fd
}

if {$argc > 0} {
    ::jg::export_json [lindex $argv 0]
} else {
    ::jg::export_json "/app/design_states_resolved.json"
}
