You are a security auditor reviewing formally verified cryptographic assembly code from the s2n-bignum library.

## Context

The s2n-bignum library provides hand-written x86-64 assembly routines for cryptographic bignum arithmetic. Each routine has a corresponding HOL Light formal verification proof file (`.ml`) that:
- Embeds the machine code as a literal byte sequence extracted from the compiled object file
- States a correctness theorem as a Hoare triple: preconditions on machine state, a postcondition guaranteeing mathematical correctness, and a frame condition listing which state components may be modified

For the verification to be sound, the byte sequence in the proof must exactly match the compiled assembly, and the theorem must faithfully capture all necessary constraints for safe cryptographic use.

## Task

The directory `/app/proofs/` contains HOL Light proof files for four cryptographic functions. The directory `/app/asm/` contains an x86-64 assembly source and its build header.

Some of the proof files have been tampered with in ways that would undermine the security guarantees of the verified code. Perform a comprehensive security audit of each proof file. Assess whether the embedded machine code is authentic, whether the formal specification provides adequate guarantees for its stated cryptographic purpose, and whether all necessary safety constraints are present.

Produce your findings as `/app/audit_report.json` with this structure:

```json
{
  "functions": {
    "<function_name>": {
      "status": "pass" | "fail",
      "issues": [
        {
          "type": "<descriptive_category>",
          "description": "<detailed finding with evidence>",
          "severity": "critical" | "high" | "medium" | "low"
        }
      ]
    }
  }
}
```

Each of the four proof files must have a corresponding entry. Functions with no soundness issues should have `"status": "pass"` and an empty issues list.