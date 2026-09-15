A binary serial capture from an embedded device is at `/app/capture.bin`. Three candidate firmware ELF images from different builds are in `/app/firmware/` (`fw_alpha.elf`, `fw_beta.elf`, `fw_gamma.elf`). Upstream decoder source code from the `defmt` framework is in `/app/reference/`.

Create `/app/decoder.py` that decodes the log frames from the capture, determines which firmware produced them, and writes:

- `/app/output.txt` — one decoded line per valid frame, sorted by timestamp: `{timestamp} {LEVEL} {message}`
- `/app/analysis.json` — with keys: `correct_firmware` (filename string), `total_frames` (int), `valid_frames` (int), `corrupt_frame_indices` (0-indexed list of frames that failed integrity checks)

Run the decoder after creating it.