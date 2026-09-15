# DO-326A Security Certification Audit — UAV-MK47 System

## Classification
DO-178C DAL-A / DO-326A Airborne Security Assessment

## System Under Test
Mixed-criticality UAV flight control system on seL4 Microkit platform.
12 protection domains spanning safety-critical flight control, network telemetry,
cryptographic services, logging, and a virtual machine monitor with legacy guest OS.

## Audit Scope
Independent verification of the isolation analysis produced by the system
integrator's tool (`/app/analyzer.py`) against the system description
(`/app/system.xml`) and security policy (`/app/policy.json`).

## Overall Verdict: FAIL
The isolation analysis tool contains defects that produce incorrect results.
The false-negative errors in policy violation detection represent unacceptable
gaps in security assurance for DAL-A flight-critical certification.

---

## Detailed Findings

### FINDING-1: Spurious dependency edges in the graph

The analyzer's dependency graph contains edges that are inconsistent with the
actual information flow properties of the seL4 capability model.

- The graph asserts that `control` depends on `telemetry`. However, examination
  of the memory mappings for the `ctrl_status` region shows that `control` maps
  it with write permission while `telemetry` maps it read-only. A domain that
  only reads from a region cannot influence a domain that writes to it.
  Penetration testing confirmed that compromising `telemetry` has no effect on
  `control` domain behavior.

- The graph asserts that `config_store` depends on `control`. The `config_data`
  region is mapped read-write by `config_store` and read-only by `control`.
  `config_store` has no outgoing dependencies in the correct analysis since no
  other domain can modify data it relies on.

### FINDING-2: Trusted Computing Base sizes are incorrect

The analyzer significantly underestimates TCB sizes. For example, `control`'s
TCB is reported as size 4 but independently verified as 5. Network-cluster
domains such as `crypto` and `eth_driver` are reported with TCB sizes of 1,
when they should each be 11 (all other domains in the system).

### FINDING-3: Impact boundary anomaly

The analyzer reports identical impact boundary sizes and TCB sizes for every
protection domain in the system. This is mathematically incorrect for a
directed graph with asymmetric reachability — a PD's TCB (set of domains it
transitively depends on) and its impact boundary (set of domains that
transitively depend on it) should generally differ unless the graph is fully
symmetric. The certification authority suspects the impact boundary computation
is not using the correct transitive dependency information, but the exact root
cause could not be determined from output analysis alone.

### FINDING-4: Bidirectional sensor-control dependency inconsistent with memory model

The analyzer shows a bidirectional dependency between `sensor` and `control`.
The `sensor_data` memory region is mapped with write access by `sensor` and
read-only access by `control`. Under the seL4 capability model, the dependency
derived from this memory mapping should be strictly unidirectional: `control`
depends on `sensor` (the reader depends on the writer), but `sensor` should
not depend on `control` through this mechanism. The bidirectional dependency
edge appears to be an artifact of the same defect described in FINDING-1 and
should be removed.

### FINDING-5: Policy violations not detected

| Violation type        | Analyzer reports | Independently verified |
|-----------------------|------------------|------------------------|
| Isolation violations  | 0                | 3                      |
| TCB size violations   | 0                | 0 (correct)            |
| Impact size violations| 0                | 3                      |

The three missed isolation violations involve safety-critical domains being
reachable from virtual machine domains, indicating potential cross-domain
attack paths from the untrusted guest OS to the flight control loop.

### FINDING-6: Implicit inter-domain coupling through shared interrupt controller

Protection domains `sensor` (IRQ 47), `actuator` (IRQ 48), and `serial_driver`
(IRQ 33) each bind hardware interrupt capabilities. Under the seL4 capability
model, interrupt capabilities are allocated by the kernel from a global IRQ
controller namespace. When PDs bind IRQs on the same GIC (Generic Interrupt
Controller) SPI bank, servicing an interrupt in one domain affects the
dispatch latency of interrupts in other domains sharing the bank.

Specifically, `sensor` and `actuator` handle consecutive IRQs (47 and 48) on
the same SPI bank (SPIs 32–63), creating an implicit timing coupling. The
analyzer should model this as a dependency edge: if `actuator`'s interrupt
processing is delayed due to `sensor`'s interrupt handler holding the kernel's
IRQ dispatch lock, `actuator`'s behavior is affected by `sensor`.

This inter-domain coupling through the interrupt controller should be
reflected in the dependency graph as a bidirectional edge between `sensor`
and `actuator`, increasing both domains' TCB sizes accordingly.

## Required Actions

The system integrator must correct the isolation analysis tool and resubmit.
The corrected tool must produce a report at `/app/report.json` using the same
JSON schema as the current tool's output.
