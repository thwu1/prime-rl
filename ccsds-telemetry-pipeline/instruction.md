A CCSDS TM telemetry processing pipeline at `/app/` reads randomized TM transfer frames from `/app/telemetry.bin` and extracts embedded CCSDS Space Packets, outputting structured JSON to `/app/output.json`. The Java source files in `/app/src/` contain conformance defects. Fix all defects so the pipeline produces correct output.

**Build and run:**
```
mkdir -p /app/bin && javac -d /app/bin /app/src/*.java && java -cp /app/bin CcsdsPipeline
```

**Protocol conformance requirements:**
- TM frame format per CCSDS 132.0-B-2: 256-byte fixed-length frames, 6-byte primary header (TFVN 2b, Spacecraft ID 10b, VCID 3b, OCF flag 1b, MCFC 8b, VCFC 8b, TFDFS 16b), optional 4-byte OCF (per header flag), 2-byte CRC-16-CCITT trailing
- Frame derandomization per CCSDS 131.0-B-3
- CRC-16-CCITT verification per CCSDS 132.0-B-3
- Space Packet extraction per CCSDS 133.0-B-1: version 0, 6-byte primary header, Packet Data Length field encodes (total_packet_length - 7)
- First Header Pointer special values: 0x7FF = no packet starts in frame, 0x7FE = idle frame; other values = byte offset of first packet within the data field
- Packets spanning frame boundaries must be correctly reassembled across consecutive frames

**Output schema** (`/app/output.json`):
```json
{
  "frames": [{"index": 0, "spacecraftId": N, "vcid": N, "mcFrameCount": N,
    "vcFrameCount": N, "firstHeaderPointer": N, "ocf": "0xHHHHHHHH",
    "crcValid": true}],
  "packets": [{"index": 0, "apid": N, "sequenceFlags": N,
    "sequenceCount": N, "dataLength": N, "userDataHex": "hex"}]
}
```

`firstHeaderPointer` is -1 when the raw FHP indicates no packet start or idle. `dataLength` is the Packet Data Length header field value. `userDataHex` is lowercase hex of the packet data field bytes (dataLength + 1 bytes).

**Success criteria:** All frame CRCs validate. Frame metadata matches actual spacecraft/channel parameters. All embedded packets are extracted with correct APIDs, sequence counts, and byte-exact data content, including packets spanning multiple frames.
