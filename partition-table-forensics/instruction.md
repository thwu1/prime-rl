Three raw ESP32 flash memory dumps are at `/app/dumps/{flash_simple.bin, flash_ota.bin, flash_complex.bin}`. Each represents a device with a different partition layout. In every dump, the partition table region (flash offset 0x8000) is damaged — fully zeroed or partially destroyed — but the actual flash contents at their original offsets are intact.

Write `/app/flash_forensics.py`, a Python CLI that recovers partition information from these corrupted dumps.

Binary format specifications are at `/app/reference/formats.txt`. The ESP-IDF partition table utility at `/app/tools/gen_esp32part.py` handles binary-to-CSV conversion, CSV-to-binary conversion, and constraint validation — study its source code and use it as an external validation oracle.

The tool must expose three subcommands:

**`scan <flash_dump>`** — Stdout: JSON `{"flash_size": <int>, "regions": [{"offset": <int>, "size": <int>, "content_type": "<app|nvs|ota_data|phy>"}, ...]}`. Consecutive sectors of identical content must appear as a single merged region.

**`reconstruct <flash_dump> <output_file>`** — Write a 0xC00-byte partition table binary that (1) passes `python3 /app/tools/gen_esp32part.py --quiet <output_file>`, and (2) survives a full gen_esp32part.py round-trip: converting the binary to CSV and then back to binary must produce a byte-identical file. Any surviving partition table entries present in the dump must be preserved and incorporated.

**`check <partition_table_binary>`** — Stdout: JSON `{"entries": [{"index": <int>, "name": <str>, "type": <int>, "subtype": <int>, "offset": <int>, "size": <int>, "flags": <int>, "valid_magic": <bool>}, ...], "md5": {"present": <bool>, "valid": <bool>}, "issues": [{"issue_type": <str>, "description": <str>}, ...]}`. Must detect constraint violations as defined by the ESP-IDF partition table specification.