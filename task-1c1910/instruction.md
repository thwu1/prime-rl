Five IEEE 802.11a WiFi frame captures are stored as binary IQ sample files in `/app/captures/`. Each `.iq` file contains baseband time-domain samples that have propagated through a frequency-selective wireless channel. The file `/app/captures/manifest.json` describes the binary format, frame structure, known reference signal values, and subcarrier layout for all captures.

Each capture encodes a complete 802.11a PHY-layer frame — including training sequences, a SIGNAL field describing the modulation and coding scheme, and DATA symbols carrying the payload. The wireless channel distorts all symbols identically within a frame.

Your goal: recover the transmitted payload from each of the five frames. The frames use different modulation and coding schemes. Write each frame's recovered payload (the PSDU content, excluding the trailing 4-byte FCS) as a lowercase hex string to `/app/decoded/frame_N.hex` (where N is 0–4). All five payloads must decode with valid CRC-32.

GNU Octave (`octave-cli`), Python 3, `xxd`, and `jq` are available in the environment.