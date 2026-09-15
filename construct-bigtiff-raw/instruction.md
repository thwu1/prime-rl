A scientific calibration pipeline has produced a BigTIFF file at `/app/corrupted.tif` containing multiple structural corruptions. Attempting to read it with `tifffile` reveals various failures: some pages may be inaccessible, some may fail to decode, and others may return incorrect pixel data.

The file originally contained 3 pages of calibration data with these deterministic pixel patterns:

- **Page 0**: 512×512, uint16, grayscale — `pixel[y, x] = (y * 512 + x) % 65536`
- **Page 1**: 256×256, uint8, RGB — `pixel[y, x] = [y % 256, x % 256, (y + x) % 256]`
- **Page 2**: 384×384, uint16, grayscale — `pixel[y, x] = (y * 3 + x * 7 + 42) % 65536`

Each page carries an `ImageDescription` tag with calibration metadata that must be preserved verbatim in the repaired output.

Diagnose all structural issues in the corrupted file and produce a fully valid repaired BigTIFF at `/app/repaired.tif` where all 3 pages are accessible with correct pixel data and preserved metadata.