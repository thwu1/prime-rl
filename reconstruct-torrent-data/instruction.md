Artifacts from a partial BitTorrent download session are preserved at `/opt/task_data/`:

- `metadata.torrent` — The torrent metainfo file for the download
- `pieces/` — Directory containing cached piece data in binary files
- `peer_traffic.log` — Raw binary stream of peer wire protocol messages captured during the session

Some pieces may be corrupt, missing, or duplicated across sources. Reconstruct as much of the original file content as possible and produce a forensic analysis at `/app/output/`.

## Expected Output

### `/app/output/report.json`

```json
{
  "info_hash": "<40-char lowercase hex>",
  "piece_length": 0,
  "total_pieces": 0,
  "total_size": 0,
  "pieces": [
    {"index": 0, "status": "valid", "hash": "<hex>"},
    {"index": 1, "status": "corrupted", "expected_hash": "<hex>", "actual_hash": "<hex>"},
    {"index": 2, "status": "missing"}
  ],
  "files": [
    {"path": "relative/path", "length": 0, "status": "complete"},
    {"path": "other/file", "length": 0, "status": "partial"}
  ]
}
```

The `pieces` array is sorted by index. Valid pieces include `"hash"`. Corrupted pieces include both `"expected_hash"` and `"actual_hash"`. Pieces sourced from multiple candidates include `"duplicates_found"`. A file's status is `"complete"` when all data covering its byte range is verified; otherwise `"partial"`.

### `/app/output/files/<torrent_name>/`

Reconstructed directory tree preserving the torrent's file structure. Verified byte ranges contain original content; unverifiable ranges are null-filled (`0x00`).