The `gen_esp32part.py` partition table utility at `/app/tools/gen_esp32part.py` was recently refactored and now contains regressions that cause valid partition tables to be rejected. The only surviving reference from the legacy product is a raw 4MB flash dump at `/app/legacy_flash.img` -- the partition table resides at the standard ESP32 offset (0x8000) within this image. The hardware specification for three target configurations is at `/app/spec.toml`.

Fix the regressions in `/app/tools/gen_esp32part.py`, then produce validated partition table binaries for each configuration. OTA application slots must be equal-sized and maximized for the available flash space, respecting the alignment constraints that the corrected tool enforces for each secure boot mode. Consult the tool's source code to understand how partition type, offset alignment, size alignment, and secure boot mode interact -- the spec intentionally omits these implementation details.

Write output files to `/app/output/`:
- `config_a.bin` (4 MB, no secure boot)
- `config_b.bin` (4 MB, secure boot v1)
- `config_c.bin` (16 MB, secure boot v2)