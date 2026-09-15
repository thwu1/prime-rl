A custom Network Diagnostic Protocol (NDP) packet dissector is at `/app/`. The C source in `/app/src/` contains three synthetic security vulnerabilities. Protocol parameters including buffer sizes are randomized per instance. An AddressSanitizer-instrumented binary is at `/app/ndp_asan` and processes packet files: `./ndp_asan <packet_file>`.

The protocol format and buffer size constants are documented in `/app/src/ndp.h`, which also contains a per-instance `CHALLENGE_TOKEN` define. Valid reference packets are in `/app/testdata/`. Unmodified source is preserved at `/app/.orig_src/`.

Your objectives:

1. **Identify all three vulnerabilities.** Write a JSON report to `/app/vulns.json` as an object with:
   - `"challenge_token"`: the value of `CHALLENGE_TOKEN` from `/app/src/ndp.h`
   - `"vulnerabilities"`: array of objects, each with `"id"` (VULN-001 through VULN-003), `"cwe"` (CWE identifier string), `"file"` (source path relative to `/app/`), `"function"` (vulnerable function name), and `"description"` (brief explanation of the flaw)

2. **Create proof-of-vulnerability inputs.** Place three binary NDP packet files (`pov1.bin`, `pov2.bin`, `pov3.bin`) in `/app/pov/` that each trigger a distinct vulnerability. Each must be a valid NDP packet with correct magic number and CRC32 checksum. Payloads must account for the actual buffer sizes in the instance's source headers.

3. **Patch the source code.** Modify files in `/app/src/` to fix all three vulnerabilities without breaking processing of valid test packets in `/app/testdata/`.

Rebuild after patching: `cd /app && make clean && make asan`.