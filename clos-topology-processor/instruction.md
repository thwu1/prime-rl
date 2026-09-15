Create `/app/topo_compiler.py` — a tool that transforms flat containerlab topologies (all properties specified directly on each node, no inheritance) into semantically equivalent factored topologies that exploit containerlab's `defaults`, `kinds`, and `groups` inheritance system to eliminate redundancy.

Usage: `python3 /app/topo_compiler.py <input.clab.yml>` → factored YAML on stdout.

Semantic equivalence means containerlab's property resolver produces identical per-node state (kind, image, type, env, labels) from both the flat input and the factored output. The resolver's behavior for different field types is defined in the Go reference source — your factoring algorithm must honor these semantics exactly, including the critical asymmetry between how scalar fields and map fields are resolved through the inheritance chain.

Reference files:
- `/app/reference/types_topology.go` — Go source showing resolution semantics (`getField`, `mergeStringMapFields`, and their call sites)
- `/app/resolver.py` — working Python resolver (importable or can be studied)
- `/app/topologies/*.flat.yml` — flat input topologies to process

The factored output must resolve identically to the flat input for every node across all fields, actively use inheritance to reduce per-node property repetition, and preserve all links unchanged.