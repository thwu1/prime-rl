An SDN configuration compiler at `/srv/sdn/sdn_compiler/` reads Proxmox-style SDN definitions (EVPN zones, VNets, subnets) from YAML configs in `/srv/sdn/configs/` and generates Linux networking commands and FRR (Free Range Routing) configurations for EVPN/VXLAN overlay networks.

The compiler has multiple interacting bugs across its FRR generation, network interface generation, and configuration validation modules. Some bugs mask others — a partial fix that appears correct in isolation will reveal a deeper structural issue when the full output is validated. The bugs produce configurations that would silently break L3 VRF routing, EVPN route exchange, VXLAN tunnel establishment, and distributed anycast gateway operation in a production EVPN fabric.

Additionally, the compiler's validator is missing a critical safety check. In VXLAN-based fabrics, every VNI (both L2 VNet tags and L3 VRF VXLAN IDs) occupies a shared namespace — a collision between an L2 VNI and an L3 VNI causes traffic crossover on the data plane, and reuse of the same L2 VNI across different zones merges their broadcast domains. Implement the missing `validate_vni_conflicts()` function in the validator module and wire it into the validation pipeline.

The test suite at `/tests/test_state.py` validates all fixes and the new feature. All tests must pass.

You can run the compiler with:
```
cd /srv/sdn && python3 -m sdn_compiler --cluster configs/cluster.yaml --sdn configs/sdn.yaml --node pve01 --output-dir /tmp/out
```