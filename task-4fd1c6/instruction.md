A network proxy configuration engine at `/app/` builds shell commands from user-supplied values (username, hostname, port) using template substitution. It runs as an HTTP service (`python3 /app/server.py`, port 9443) exposing three POST endpoints — `/exec_proxy`, `/direct_tunnel`, `/checked_health` — each accepting a JSON body `{"username": "...", "hostname": "...", "port": "..."}`. Query `GET /status` for endpoint and format documentation.

Each endpoint applies a different metacharacter sanitizer before passing the assembled command to `bash -c`:
- **exec_proxy** and **checked_health**: Python-based sanitizers in `/app/engine.py`
- **direct_tunnel**: compiled binary filter at `/app/bin/sanitize_direct` (no source code available — only the stripped ELF binary is present)

All three sanitizers are vulnerable to command injection despite their filtering.

**Deliverables:**

1. **Exploit payloads**: For each of the 3 contexts, write `/app/exploits/<context_name>.json` (i.e., `exec_proxy.json`, `direct_tunnel.json`, `checked_health.json`) containing a JSON object with keys `"username"`, `"hostname"`, and `"port"` (all strings). Each exploit must bypass its context's vulnerable sanitizer (the payload must pass through the sanitizer without triggering a `ValueError`) and, when the resulting command is executed via `bash -c`, create a marker file at `/tmp/pwned_<context_name>` (e.g., `/tmp/pwned_exec_proxy`).

2. **Binary analysis report**: Reverse-engineer the compiled sanitizer binary at `/app/bin/sanitize_direct` and write:
   - `/app/analysis/blocklist.txt`: the exact set of characters used by the binary's blocklist filter (single line, the characters themselves, no trailing whitespace). The test verifies the character set matches what `strings` extracts from the binary.
   - `/app/analysis/build_id.txt`: the internal build identifier string embedded in the binary (single line, no trailing whitespace). The identifier follows the pattern of an alphabetic prefix, a dash, and an alphanumeric suffix (e.g., `ABCD-1234abcd5678`). The test verifies it matches the identifier found via `strings` on the binary.

3. **Hardened sanitizer**: Create `/app/sanitizer_fixed.py` exporting a function `sanitize(value: str) -> str` with the following exact contract:
   - **Returns** the input string unchanged if it is valid.
   - **Raises `ValueError`** if the input is invalid.
   - **Rejects** empty strings (raises `ValueError`).
   - **Rejects** any string containing ASCII control characters (code points 0x00–0x1F and 0x7F), including but not limited to: null bytes, tabs, newlines (`\n`), carriage returns (`\r`).
   - **Rejects** spaces and shell metacharacters such as `;`, `` ` ``, `|`, `$`, `(`, `)`, `[`, `]`, `{`, `}`, `<`, `>`, `&`, `'`, `"`.
   - **Allows** only characters in the set: ASCII letters (`a-zA-Z`), digits (`0-9`), dot (`.`), underscore (`_`), at-sign (`@`), colon (`:`), forward slash (`/`), and hyphen (`-`).
   - Must block all three exploit payloads (at least one field of each exploit must trigger `ValueError`).
   - Must allow legitimate proxy configuration values including: simple usernames (e.g., `john.doe`, `my_user`), email-style usernames (e.g., `user@domain`), FQDNs (e.g., `proxy.example.com`, `web-proxy-01.dc1.example.com`), IPv4 addresses (e.g., `192.168.1.1`), and numeric ports (e.g., `8080`).