# Mission Change Requirements: CDH-2024-07

## Background

The current flight software topology provides basic command and data handling
(CDH) for a satellite platform. A mission change requires adding a file
downlink subsystem for data product retrieval and enhancing command path
redundancy with a backup command dispatcher.

## REQ-1: File Downlink Subsystem

Add instances `fileDownlink` (component `Svc.FileDownlink`) and `bufferMgr`
(component `Svc.BufferManager`) to the topology.

- `fileDownlink` must be scheduled by the 10 Hz rate group for timely data
  product downlink.
- `fileDownlink` requires buffer allocation and return services from `bufferMgr`.
  Consult the component port definitions in `components.json` to determine the
  appropriate connections.
- `fileDownlink` must register with both command dispatchers (primary and
  backup).
- `fileDownlink` is an active component that must participate in all standard
  F-Prime infrastructure patterns (see REQ-4).

## REQ-2: Backup Command Dispatcher

Add instance `backupCmdDisp` (component `Svc.CommandDispatcher`) to provide a
redundant command path.

- The backup dispatcher must be able to dispatch commands to every
  command-bearing component in the topology. A component is command-bearing if
  it has both a command input port and a command registration output port.
- All existing command-bearing components and `fileDownlink` must be reachable
  from `backupCmdDisp`.
- Command registration for `backupCmdDisp` uses a topology-level init routine
  that is **not modeled as port connections**. Therefore, only command dispatch
  connections from `backupCmdDisp` to target components are needed; command
  registration port connections to `backupCmdDisp` are not required.
- The `CommandDispatcher`'s match specifier constraints apply only at indices
  where both matched ports are connected.
- `backupCmdDisp` does NOT interface with command sequences (no sequence
  command buffer or status connections).
- `backupCmdDisp` is an active component that must participate in health
  monitoring and all infrastructure patterns (see REQ-4).

## REQ-3: Scheduling Feasibility

The redesigned topology must satisfy all rate-group CPU budget constraints
defined in `/app/spec/runtime.json`. If adding `fileDownlink` to the 10 Hz rate
group causes a budget overrun, components must be rebalanced between rate
groups. Both `health.Run` and `tlmChan.Run` are time-critical and must remain
in the 10 Hz group. Any rebalancing decision must be documented in the design
decisions output.

## REQ-4: Infrastructure Wiring Standards

Every active or queued component in the topology must have the following
connections where the component defines the corresponding ports:

- **Health monitoring**: Connected to `health` via `PingSend`/`PingReturn`
  pairs with correct index matching (`match PingSend with PingReturn`).
- **Telemetry**: Telemetry output ports → `tlmChan.TlmRecv`.
- **Event logging**: Event log output ports → `eventLog.LogRecv`.
- **Text event logging**: Text event output ports → `eventLog.TextLogRecv`.
- **Time**: Time output ports → `timeSrc.timeGetIn`.

Passive components (eventLog, timeSrc, bufferMgr) do not require health
monitoring but must have infrastructure connections for any ports they define.

## REQ-5: Topology Visualization

Produce a Graphviz DOT file (`/app/topology.dot`) visualizing the complete
redesigned topology. Requirements:

- Each component instance is a node.
- Edges represent connections, colored by pattern type:
  - Command connections (Fw.Cmd, Fw.CmdReg, Fw.CmdResponse, Fw.Com): `red`
  - Health connections (Svc.Ping): `green`
  - Telemetry connections (Fw.Tlm, Fw.TlmGet): `blue`
  - Event connections (Fw.Log, Fw.LogText): `orange`
  - Time connections (Fw.Time): `purple`
  - Scheduling connections (Svc.Sched, Svc.Cycle): `brown`
  - Data connections (Fw.BufferSend, Fw.BufferGet): `black`
- Render the DOT file to SVG at `/app/topology.svg`.

## REQ-6: Scheduling Analysis

Produce `/app/scheduling_report.json` with the following structure for each
rate group:

```json
{
  "rg10Hz": {
    "period_ms": 100,
    "budget_ms": 70,
    "members": [{"instance": "...", "port": "...", "wcet_ms": ...}, ...],
    "total_wcet_ms": ...,
    "utilization_pct": ...,
    "feasible": true/false
  },
  ...
}
```

## REQ-7: Design Decisions

Produce `/app/design_decisions.json` — a JSON array of objects, each with keys
`"decision"` and `"rationale"`. Include at least 3 entries documenting:
- Any rate-group rebalancing performed
- Health monitoring index assignments for new components
- Command dispatcher wiring choices
