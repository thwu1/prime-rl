You are auditing embedded firmware source code in `/app/`. The codebase implements cryptographic operations — encryption, decryption, authentication, HMAC signing, and key derivation. The developers believed they followed security best practices for handling sensitive material. However, the compiled binary (built with `make -C /app`, producing `/app/build/secure_firmware`) contains multiple distinct classes of security vulnerabilities that are invisible when reading the source code alone. The binary must exit with code 0 after your fixes.

An unmodified copy of the original source is preserved at `/app/reference/secure_ops_vulnerable.c`.

Identify and fix all security vulnerabilities in `/app/src/secure_ops.c`. Your fixes must be effective not just at the source level, but in the actual compiled binary — you should verify this yourself at the assembly level.

Create an executable automated verification tool at `/app/verify_security.sh` that accepts a binary path as its first argument (default: `/app/build/secure_firmware`) and outputs a JSON report to stdout with this schema:

```json
{"binary": "<path>", "vulnerabilities_found": <int>, "vulnerabilities": [{"function": "<name>", "type": "<type>", "description": "<detail>"}], "secure": <bool>}
```

The tool must correctly detect vulnerabilities in the original binary (built from the reference source) and confirm zero vulnerabilities in your fixed binary.

Write a design rationale at `/app/design_rationale.md` evaluating at least 4 distinct mitigation strategies for each vulnerability class you identified, analyzing whether each approach is effective under the project's current compilation settings and why. Discuss portability, performance, and correctness trade-offs. Justify your chosen approach.