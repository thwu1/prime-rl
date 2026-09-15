Two stripped ELF64 binaries at `/app/crackme_alpha` and `/app/crackme_beta` implement serial key verification through custom stack-based virtual machines with XOR-encrypted bytecode. A standalone VM runner at `/app/vm_runner` executes arbitrary bytecode files using the same instruction set architecture.

Interfaces:
- `/app/crackme_alpha <username> <serial_hex>` — outputs `ACCESS GRANTED` or `ACCESS DENIED`
- `/app/crackme_beta <username> <serial_hex>` — same
- `/app/vm_runner <bytecode_file> <xorkey_file> <username> <serial_hex>` — loads and runs external encrypted bytecode

Produce the following deliverables:

1. `/app/keygen_alpha.py` — single arg: username. Prints valid lowercase hex serial (no `0x` prefix) for `crackme_alpha`. Must work for any 1-64 char ASCII username.

2. `/app/keygen_beta.py` — same interface, for `crackme_beta`.

3. `/app/keygen_universal.py` — two args: binary_path, username. Auto-detects crackme variant by analyzing binary contents, prints valid serial.

4. `/app/gamma.bc` — encrypted VM bytecode implementing a novel key derivation algorithm using the same ISA as alpha/beta. Requirements:
   - At least 3 distinct cryptographic mixing stages using algorithms and constants not found in either alpha or beta
   - At least one anti-analysis technique (opaque predicate, dead code path, etc.)
   - Good avalanche properties: a single-character input change must flip >35% of output bits on average

5. `/app/gamma_key.bin` — the 4-byte XOR decryption key for `gamma.bc`.

6. `/app/keygen_gamma.py` — single arg: username. Prints valid serial accepted by `/app/vm_runner /app/gamma.bc /app/gamma_key.bin <username> <serial>`.

7. `/app/audit.json` — security audit comparing all three schemes with structure:
   - `schemes` object with keys `alpha`, `beta`, `gamma`, each containing: `key_derivation_stages` (int), `algorithms_used` (list of strings), `anti_analysis_techniques` (list, empty if none), `avalanche_quality` (one of `"poor"`, `"moderate"`, `"good"`, `"excellent"`), `estimated_re_hours` (float)
   - `ranking`: ordered list of scheme name strings from strongest to weakest
   - `ranking_justification`: string (>=200 characters) with detailed technical reasoning
   - `attack_vectors` object with keys `alpha`, `beta`, `gamma`, each a list of identified weaknesses/attack surfaces