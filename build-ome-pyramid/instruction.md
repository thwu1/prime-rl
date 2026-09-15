Raw fluorescence microscopy data from a 4-channel spinning-disk confocal experiment is stored in `/app/acquisition/` as channel-separated raw binary files. Each channel uses a different binary format dictated by its detector subsystem — including big-endian integer streams, floating-point data behind an ASCII instrument header, column-major raster dumps with spatial drift, and packed 12-bit integer storage. The acquisition log at `/app/acquisition/acquisition_log.txt` documents the instrument configuration and per-channel binary format details. Output parameters and physical calibration are in `/app/acquisition/calibration.json`.

Write `/app/assemble.py` that reads each channel's raw binary data according to the acquisition log, applies all necessary format conversions and spatial corrections, assembles a unified TCZYX uint16 volume, builds a multi-resolution image pyramid with area-averaged downsampling, and writes the result as a pyramidal OME-TIFF to `/app/output.ome.tif`. The output must use BigTIFF format, tiled pages (256x256), deflate compression, SubIFD-based pyramid levels, a thumbnail series, and complete OME-XML metadata (physical pixel sizes, channel names, time interval).

Also produce `/app/analysis.json` conforming to the schema below.

## analysis.json schema

```json
{
  "dimensions": {
    "T": <int>,
    "C": <int>,
    "Z": <int>,
    "Y": <int>,
    "X": <int>
  },
  "channels": [
    {
      "name": <string>,
      "min": <number>,
      "max": <number>,
      "mean": <number>,
      "std": <number>
    }
  ],
  "pyramid_levels": [
    {
      "level": <int>,
      "shape": [<int>, <int>, <int>, <int>, <int>],
      "downsample_factor": <int>
    }
  ],
  "format": {
    "type": <string>,
    "compression": <string>,
    "tile_size": [<int>, <int>]
  }
}
```

Field definitions:

- `dimensions`: the assembled volume's axis sizes. Keys are exactly `T`, `C`, `Z`, `Y`, `X` (integers).
- `channels`: array with one entry per channel in acquisition order. `name` is the channel label from the acquisition log. `min`, `max`, `mean`, `std` are the intensity statistics of that channel across the full TZYX volume (computed on the assembled uint16 data). All are numeric (min/max are integers, mean/std are floats).
- `pyramid_levels`: array with one entry per resolution level (including base). `level` is the 0-based index. `shape` is the 5-element TCZYX dimension list (integers). `downsample_factor` is the spatial reduction factor relative to the base level (1 for base, 2 for first downsample, 4 for second, etc.).
- `format`: describes the output file format. `type` must be `"BigTIFF"`. `compression` must be `"deflate"`. `tile_size` is `[height, width]` as integers.