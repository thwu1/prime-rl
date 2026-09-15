# FPP Topology Connection Rules Reference

## F-Prime Architecture Overview

F-Prime (F') is NASA's component-based flight software framework. Components
communicate through typed ports. A **topology** defines component instances and
the port connections between them.

### Key Architectural Patterns

- **Rate Groups**: A `RateGroupDriver` receives a hardware timer tick and fans
  it out to `ActiveRateGroup` instances (one per rate). Each ActiveRateGroup
  dispatches `Svc.Sched` calls to its member components via
  `RateGroupMemberOut` ports.

- **Command Dispatch**: A `CommandDispatcher` receives serialised command buffers
  from command sources (e.g. `CmdSequencer`) on its `seqCmdBuff` input ports
  and dispatches decoded commands to target components via `compCmdSend` output
  ports. Target components register their opcodes through `compCmdReg` and
  return execution status through `compCmdStat`. The dispatcher uses **port
  matching** (`match compCmdSend with compCmdReg`) to guarantee that a command
  sent on index *i* reaches the same component that registered on index *i*.

- **Health Monitoring**: The `Health` component periodically pings active
  components via `PingSend` and expects keyed replies on `PingReturn`. It uses
  `match PingSend with PingReturn` to pair outgoing pings with incoming
  replies at the same array index.

- **Telemetry**: Components emit telemetry values on `Fw.Tlm` output ports,
  routed to `TlmChan` for storage and downlink.

- **Events**: Components emit structured event records on `Fw.Log` ports and
  human-readable text on `Fw.LogText` ports, both routed to passive loggers.

- **Time**: Components obtain timestamps by invoking their `Fw.Time` output
  port, which connects to a time-source component's sync input.

---

## Connection Rules

### Rule 1 -- Port Direction

Every connection must go **from an output port to an input port**.

| Source direction | Target direction | Valid? |
|-----------------|-----------------|--------|
| output          | input           | YES    |
| input           | output          | NO     |
| input           | input           | NO     |
| output          | output          | NO     |

### Rule 2 -- Port Type Compatibility

Both endpoints of a connection must use the **same port type**, with one
exception for serial ports:

* Two typed ports: types must match exactly (e.g. `Fw.Cmd` <-> `Fw.Cmd`).
* One serial port + one typed port: allowed **only if** the typed port's type
  has `has_return_type = false`. Connecting a serial port to a typed port whose
  type has a return value is forbidden.

### Rule 3 -- Port Array Bounds

Each port declaration includes an array `size` (minimum 1). Indices are
**zero-based**. Any connection referencing `index >= size` is out of bounds.

### Rule 4 -- Output Port Uniqueness

Each `(instance, output_port_name, index)` triple may appear as the **source**
of **at most one** connection. Duplicate output usage is forbidden.

Multiple connections **to** the same input port index from different sources
are permitted.

### Rule 5 -- Port Name Validity

Every connection must reference port names that actually exist in the
component definition of the corresponding instance. A connection citing a
non-existent port name is invalid.

### Rule 6 -- Port Matching

A component definition may declare **match specifiers**:

```
match <output_port> with <input_port>
```

Both ports belong to the same component and have the same array size. The
constraint is:

> For every index *i* where **both** ports are connected, let *X* be the
> remote instance on the other end of `output_port[i]` (i.e. the target),
> and *Y* be the remote instance on the other end of `input_port[i]`
> (i.e. the source). The match requires **X = Y**.

This guarantees that paired operations -- such as dispatching a command
and receiving the registration for that command -- always involve the same
remote component at each array slot.
