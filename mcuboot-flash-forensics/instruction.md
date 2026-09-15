An nRF52840-based device is stuck in a boot loop after a failed OTA firmware update. A raw 1MB flash dump is at `/app/flash_dump.bin`. The nRF Connect SDK Partition Manager layout is at `/app/build_config/pm_static.yml` and the MCUboot Kconfig overlay is at `/app/build_config/mcuboot.conf`.

Determine why the device cannot boot. Create `/app/analyze.sh` (sole entry point; may call helper scripts) that, when run via `bash /app/analyze.sh`, produces:

- `/app/extracted/primary.bin` — full primary image slot contents from the flash dump (size must match the partition configuration)
- `/app/extracted/secondary.bin` — full secondary image slot contents from the flash dump (size must match the partition configuration)
- `/app/extracted/checksums.txt` — SHA256 checksums of the two extracted slot files
- `/app/report.json` — forensic report conforming to the schema below

Partition offsets and sizes must be derived from `pm_static.yml`, not hardcoded.

`/app/report.json` schema:

```json
{
  "partition_layout": {
    "primary_offset": "<int>",
    "primary_size": "<int>",
    "secondary_offset": "<int>",
    "secondary_size": "<int>"
  },
  "primary_slot": {
    "offset": "<int>",
    "header_valid": "<bool>",
    "version": "<major>.<minor>.<revision>+<build>",
    "image_size": "<int>",
    "flags": "<int>",
    "hash_valid": "<bool>",
    "stored_hash": "<hex>",
    "computed_hash": "<hex>"
  },
  "secondary_slot": { "...same fields as primary_slot..." },
  "primary_trailer": {
    "magic_valid": "<bool>",
    "swap_type": "<none|test|perm|revert>",
    "copy_done": "<bool>",
    "image_ok": "<bool>"
  },
  "secondary_trailer": { "...same fields as primary_trailer..." },
  "diagnosis": {
    "boot_failure_reason": "<concise identifier covering the root cause>",
    "swap_state": "<description of current boot swap state>"
  }
}
```

Run: `bash /app/analyze.sh`