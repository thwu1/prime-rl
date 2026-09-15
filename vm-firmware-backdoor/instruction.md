`/app/ooovm` is a custom stack-based virtual machine interpreter (source: `/app/ooovm.c`, compiled with debug symbols). Three authentication firmware modules are provided: `/app/auth_alpha.bin`, `/app/auth_beta.bin`, and `/app/auth_gamma.bin`.

Running `/app/ooovm <firmware>` prompts for a 16-character lowercase hex token and responds `AUTHENTICATED` or `DENIED`. All three modules contain distinct security vulnerabilities belonging to different vulnerability classes. One of the three contains an intentional backdoor (hidden alternate authentication path constituting deliberate sabotage).

Audit all three firmware modules and produce:

1. `/app/audit.json` — A JSON object with keys `"alpha"`, `"beta"`, and `"gamma"`, each containing:
   - `"vulnerability_class"`: descriptive category name
   - `"cwe"`: applicable CWE identifier (e.g. `"CWE-79"`)
   - `"exploit_token"`: a 16-character hex string that achieves `AUTHENTICATED` when piped to `/app/ooovm <firmware>` for that module
   - `"root_cause"`: one-sentence explanation of the flaw
   - `"cvss_vector"`: CVSS 3.1 base vector string beginning with `"CVSS:3.1/"` and including all eight base metrics: AV, AC, PR, UI, S, C, I, A
   - `"cvss_score"`: numeric CVSS 3.1 base score in the range [0.0, 10.0]. The intentional backdoor vulnerability must be scored at critical severity (>= 9.0)

   The gamma exploit token must be distinct from the module's legitimate authentication key — it must demonstrate that a fundamentally different input can bypass authentication due to the vulnerability.

   Also include:
   - `"risk_ranking"`: ordered JSON array of all three firmware names (`"alpha"`, `"beta"`, `"gamma"`) from most to least critical. The firmware containing the intentional backdoor must be ranked first (most critical), as deliberate sabotage is categorically more severe than implementation weaknesses.
   - `"ranking_justification"`: comparative reasoning for the severity ordering, addressing attack complexity, impact scope, and whether the flaw suggests intentional compromise vs. implementation weakness

2. `/app/auth_alpha_patched.bin` — A patched version of `auth_alpha.bin` with exactly the same file size that eliminates its vulnerability while preserving legitimate authentication. Must retain a valid OOOV format header and must reject both the exploit token and arbitrary invalid tokens (e.g. all-zero input).

3. `/app/auth_gamma_patched.bin` — A hardened replacement for `auth_gamma.bin` (valid OOOV format header) that fixes the fundamental authentication flaw. Must authenticate the same legitimate key as the original while rejecting both inputs that exploit the original vulnerability and arbitrary invalid tokens.