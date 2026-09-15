Two stripped, statically-linked x86-64 ELF binaries at `/app/license_check_alpha` and `/app/license_check_beta` each validate license keys. Both read a username and a license key from stdin (one per line) and print `VALID` or `INVALID` to stdout. Keys use the format `xxxx-xxxx-xxxx-xxxx` (four groups of four lowercase hex digits separated by dashes).

One of these binaries has a critical security flaw that the other does not share. Reverse-engineer both, assess their security properties, and deliver the following files:

- `/app/keygen_alpha.py` and `/app/keygen_beta.py` — Python scripts that each accept a username as a command-line argument and print a valid license key to stdout. Must work for any non-empty printable ASCII username up to 64 characters.

- `/app/analysis.json` — JSON with `"weak_scheme"` (`"alpha"` or `"beta"`), `"effective_bits"` (integer — effective entropy of the weak scheme in bits), `"reason"` (technical explanation of the flaw and why the other scheme is not affected).

- `/app/find_collision.py` — demonstrates the weakness by finding two distinct printable ASCII usernames (1–64 chars) that map to the same license key under the weak scheme. Writes `/app/collision.json` with `"username1"`, `"username2"`, and `"key"`.

- `/app/license_check_patched.c` — a hardened C replacement for the weak binary that eliminates its vulnerability while preserving all other components of its key derivation pipeline unchanged. Only the vulnerable component may be modified. Must compile cleanly with `gcc -O2 -static -s -o /app/license_check_patched /app/license_check_patched.c`.

- `/app/keygen_patched.py` — keygen for the patched binary (same CLI interface).

- `/app/audit.json` — comparative security evaluation of all three schemes (`alpha`, `beta`, `patched`). Contains `"schemes"`: array of three objects each with `"name"`, `"hash_width_bits"` (int), `"collision_complexity"` (Big-O string), `"key_space_bits"` (int), `"verdict"` (`"secure"` or `"insecure"`), and `"justification"`. Also `"recommended_scheme"` and `"recommendation_rationale"`.