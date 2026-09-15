# Reference Materials

This directory contains Cilium documentation and source code references for
understanding CiliumNetworkPolicy evaluation semantics.

## Files

- `policy_types.go` — Go type definitions for the CiliumNetworkPolicy API,
  adapted from github.com/cilium/cilium. The doc comments on each type and
  field describe the intended behavior.

- `policy_enforcement.md` — Reference documentation on Cilium's policy
  enforcement model, rule structure, entity definitions, and default deny
  activation.
