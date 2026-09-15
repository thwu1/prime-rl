# IMGP Parser — External Security Audit Summary

Five vulnerabilities have been identified in the IMGP image parser.
Each finding is assigned an internal tracking identifier for MAGMA
instrumentation. Full root-cause analysis and trigger condition
derivation must be performed by the instrumentor.

| ID     | CWE     | Affected Function | Severity |
|--------|---------|-------------------|----------|
| IMG001 | CWE-190 | parse_header      | High     |
| IMG002 | CWE-193 | apply_palette     | Medium   |
| IMG003 | CWE-195 | apply_offsets     | High     |
| IMG004 | CWE-120 | parse_offsets     | Medium   |
| IMG005 | CWE-787 | apply_rle         | High     |
