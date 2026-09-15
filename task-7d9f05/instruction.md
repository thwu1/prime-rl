`/app/target.o` is an x86-64 ELF object file containing two functions (`hash_entries` and `feistel_round`), compiled from C source with:

```
gcc -c -O0 -fno-stack-protector -fno-pic -fcf-protection=none -std=c11
```

`/app/candidate.c` is a functionally equivalent decompilation of these functions. It contains numerous source-level differences from the original — some produce different machine code at `-O0` (codegen-affecting), others are purely cosmetic and generate identical instructions despite looking different in source.

You must do both of the following:

**1. Match:** Modify `/app/candidate.c` so its `.text` section is byte-identical to `/app/target.o` when compiled with the same flags. Only fix codegen-affecting differences. Leave cosmetic differences untouched — they must remain in the final source.

**2. Classify:** Write your classification of every source-level difference to `/app/analysis.json`:

```json
{
  "codegen_affecting_count": <int>,
  "cosmetic_count": <int>,
  "differences": [
    {
      "description": "<what differs>",
      "classification": "codegen" | "cosmetic",
      "reason": "<why it does or does not affect -O0 codegen>"
    }
  ]
}
```

Constraints:
- No inline assembly (`asm`, `__asm__`, `__asm`)
- Function signatures and struct definitions must remain unchanged
- Cosmetic differences must be preserved in the modified source