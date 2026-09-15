A 4-dimensional float32 microscopy dataset is stored at `/app/dataset.npy` as a NumPy array with shape `(T=2, Z=3, Y=128, X=192)` and dtype `float32` (single-channel grayscale). If the file is missing from `/app/`, a backup exists at `/opt/dataset_backup.npy`.

Write a Python program `/app/lzw_tiff_writer.py` that reads this array and produces a valid **BigTIFF** file at `/app/output.tif`, then writes a JSON metrics report to `/app/report.json`.

The program must construct the TIFF binary from scratch — only Python standard library modules (`struct`, `io`, `array`, `hashlib`, `json`, etc.) and `numpy` may be used. No TIFF I/O libraries (tifffile, Pillow, libtiff bindings, imagecodecs, etc.) and no LZW/compression libraries may be imported.

## Output file requirements

- **BigTIFF** format: byte order `II` (little-endian), magic number 43, 64-bit offsets.
- **6 pages** in the main IFD chain (one per T×Z combination, ordered T-major: T0Z0, T0Z1, T0Z2, T1Z0, T1Z1, T1Z2).
- **Tiled storage**: 64×64 pixel tiles.
- **Floating-point predictor** (TIFF tag 317 = 3): for each row of a tile, reorder the bytes by grouping all bytes at the same position within each float32 sample — MSB plane first (byte 3 of all samples, then byte 2, byte 1, byte 0) — then apply horizontal byte-level differencing on the entire reordered stream (differencing crosses byte-plane boundaries).
- **LZW compression** (TIFF tag 259 = 5): each predicted tile compressed using TIFF-variant LZW with MSB-first (big-endian) code packing, starting at 9-bit codes, clear code = 256, EOI code = 257. Implement the encoder from scratch.
- Each page must have correct TIFF tags: `BitsPerSample`=32, `SampleFormat`=3 (IEEEFP), `SamplesPerPixel`=1, `PhotometricInterpretation`=1 (MinIsBlack), `Compression`=5, `Predictor`=3, `TileWidth`=64, `TileLength`=64.

## Metrics report (`/app/report.json`)

After writing the TIFF, compute and write a JSON object to `/app/report.json` with these fields:

- `predicted_data_sha256`: SHA-256 hex digest of **all predictor output bytes concatenated** (before LZW compression), in page order (T-major), row-major tile order within each page. Each tile's predictor output is the full `tile_h * tile_w * 4` bytes after byte-plane reordering and horizontal differencing.
- `per_page_compressed_bytes`: a list of 6 integers — each being the total compressed byte count (sum of all tile compressed sizes) for that page, in page order.
- `total_compressed_bytes`: the integer sum of all compressed tile sizes across all pages.

Run as:

```
python3 /app/lzw_tiff_writer.py /app/dataset.npy /app/output.tif
```