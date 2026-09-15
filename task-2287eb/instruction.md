A stripped (no symbols) ARM Cortex-M4 firmware binary is at `/app/firmware.elf`. An algorithm specification at `/app/spec.md` describes the intended keyed hash function the firmware should implement. The firmware's actual implementation deviates from the specification in exactly three places.

Reverse-engineer the firmware, determine its actual output, independently compute the spec-compliant output, and identify all deviations between the firmware and the specification.

Write your findings to `/app/analysis.json`:

```json
{
  "firmware_output": "<32-char lowercase hex string: actual firmware output>",
  "spec_output": "<32-char lowercase hex string: output of spec-compliant algorithm>",
  "deviations": [
    {
      "parameter": "<human-readable description of the differing parameter>",
      "spec_value": <integer: value specified in spec.md>,
      "firmware_value": <integer: value used by the firmware>
    }
  ]
}
```

The firmware communicates results via BKPT #255 syscalls as described in `/app/spec.md`. Concatenate all bytes emitted by BKPT #255 calls to obtain the firmware output. Tools available include `arm-none-eabi-objdump` and `arm-none-eabi-readelf`.