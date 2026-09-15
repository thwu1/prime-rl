Implement an ARMv7-M Memory Protection Unit (MPU) region allocator that computes memory isolation configurations for a Tock-like embedded operating system with multiple mutually-distrustful processes.

The memory layout specification is at `/app/memory_map.json`, describing kernel and process flash/RAM regions (addresses as integers; kernel flash at 0x00000000, kernel RAM at 0x20000000, process regions above those). Your allocator must produce `/app/mpu_config.json` containing valid PMSAv7 MPU region configurations that isolate each process.

**ARMv7-M PMSAv7 MPU constraints:**

- Region sizes must be powers of 2 (minimum 32 bytes).
- Region base addresses must be naturally aligned to region size (`base % size == 0`).
- Each region is divided into 8 equal subregions. A Subregion Disable (SRD) bitmask controls which are active: bit N set means subregion N is **disabled** (memory not granted). The SRD value is an integer 0–255.
- Maximum 8 MPU regions per process.

**Output format** (`/app/mpu_config.json`):

```json
{
  "<process_name>": {
    "regions": [
      {
        "base_address": <int>,
        "region_size": <int>,
        "subregion_disable": <int 0-255>
      }
    ]
  }
}
```

**Correctness requirements:**

1. **Coverage**: Every byte of each process's allocated flash and RAM must fall within an enabled (not SRD-disabled) subregion of that process's configuration.
2. **Isolation**: No enabled subregion of any process may overlap with kernel memory or any other process's allocated flash or RAM.
3. **Validity**: All hardware constraints satisfied; no fully-disabled (SRD=0xFF) regions.
4. **Efficiency**: Total over-granted memory must be bounded (not exceeding 100% of total allocated).

The memory map includes ranges that cross power-of-2 alignment boundaries. A naive single-region allocation for such ranges will produce regions whose enabled subregions overlap with neighboring processes' memory, violating isolation. The allocator must detect these cases and split ranges into multiple MPU regions.