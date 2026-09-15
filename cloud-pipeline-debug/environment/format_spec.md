# Sensor Calibration File Format (.cal)

Binary format for per-band radiometric calibration coefficients used to
convert raw digital numbers (DN) to top-of-atmosphere (TOA) reflectance.

## File Structure

All multi-byte numeric fields use network byte order (big-endian, most
significant byte first).

| Offset | Size (bytes) | Type | Description |
|--------|-------------|------|-------------|
| 0 | 4 | char[4] | Magic number: ASCII `SCAL` |
| 4 | 2 | uint16 | Format version (currently 1) |
| 6 | 2 | uint16 | Number of spectral bands (N) |
| 8 | N x 32 | BandEntry[] | Per-band calibration entries |

### BandEntry (32 bytes each)

| Offset | Size | Type | Description |
|--------|------|------|-------------|
| 0 | 16 | char[16] | Band name, null-padded ASCII (e.g. `B02`) |
| 16 | 8 | float64 | Gain coefficient (multiplicative factor) |
| 24 | 8 | float64 | Offset coefficient (additive term) |

## Calibration Formula

```
TOA_reflectance = gain × DN + offset
```

Where DN is the raw digital number read from the corresponding band TIF file.

## File Inventory

One `.cal` file per chip, stored in `/app/data/calibration/` and named
`<chip_id>.cal`. Calibration coefficients are per-chip and may vary
between chips (sensor-level calibration with per-acquisition adjustments).

## Usage Notes

- Calibrated reflectance values are floating-point and may fall outside [0, 255]
- All spectral analysis should be performed on calibrated TOA values, not raw DN
- Band names in the file may not follow alphabetical order
