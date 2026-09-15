A stripped native binary `/app/vm` implements a custom virtual machine that executes bytecode programs. Three bytecode programs are provided in `/app/candidates/`: `alpha.bin`, `beta.bin`, and `gamma.bin`. Each implements a different block cipher variant operating on 16-byte blocks. The file `/app/encrypted.bin` contains a 16-byte ciphertext produced by exactly one of these candidates encrypting an unknown ASCII plaintext.

Partial notes about the VM architecture are in `/app/notes.txt`. These notes are incomplete — several opcodes used by the candidates are not documented.

Determine which candidate produced the ciphertext, recover the original plaintext, and justify your conclusion.

Write the recovered plaintext as raw ASCII to `/app/answer.txt` (no trailing newline).

Write your justification to `/app/report.json` with this structure:
```json
{
  "selected_candidate": "<alpha|beta|gamma>",
  "alpha_description": "<what cipher algorithm alpha implements>",
  "beta_description": "<what cipher algorithm beta implements>",
  "gamma_description": "<what cipher algorithm gamma implements>",
  "evidence": "<why the selected candidate is correct and the others are ruled out>"
}
```

The VM can be executed with: `/app/vm <program.bin> [input_file] [output_file]`