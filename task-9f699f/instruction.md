Build `/app/optimizer.py` that computes optimized flash programming plans for embedded microcontrollers, minimizing erase operations by accounting for the current flash memory contents.

## Background

Flash memory in embedded microcontrollers is organized into regions with specific erase and programming constraints. Erasing resets an entire sector to a uniform byte value (chip-specific, often `0xFF` but not always). Programming can modify individual pages but only transitions bits in one direction — reversing a bit requires erasing the entire containing sector. Since flash sectors have limited erase endurance, skipping unnecessary erases is critical for device longevity.

## Environment

- `/app/targets/*.yaml` — probe-rs target description files defining chip memory maps, sector geometries, page sizes, and erased byte values
- `/app/firmware/` — firmware images in Intel HEX (`.hex`) and Motorola S-record (`.srec`) formats
- `/app/current_state/` — raw binary dumps of flash memory contents, one file per scenario; each file contains all NVM regions' data concatenated in ascending start-address order
- Installed packages: `srecord` (format conversion tools), `binutils` (binary analysis tools)

## CLI

```
python3 /app/optimizer.py --target <yaml> --variant <name> --firmware <file> --current-state <bin> --output <json>
```

Exit 0 on success. Exit 1 if any firmware byte falls outside defined flash regions.

## Output

JSON object with `target` (family name from YAML), `variant`, `operations` (array), `statistics` (object).

Each operation: `{"type": "erase"|"program", "region": "<name>", "address": <int>, "size": <int>}`.
Ordering: all erase operations first (sorted by region name, then address), then all program operations (sorted likewise).

Statistics fields:
- `total_erase_size`, `total_program_size` — total bytes erased/programmed
- `sectors_erased` — sectors that required erase
- `sectors_skipped` — sectors containing pages to program where erase was avoidable given the current flash state
- `pages_programmed` — number of page write operations
- `fill_bytes` — total padding bytes added to partially-filled pages
- `regions_used` — sorted list of NVM region names with operations
- `bytes_changed` — total bytes differing between the original current state and the desired state within programmed pages