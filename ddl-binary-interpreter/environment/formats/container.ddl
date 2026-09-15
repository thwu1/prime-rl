-- Chunk-based container format "DPK"
-- Magic: 0x44 0x50 0x4B, then version byte, chunk count, and chunks

def DataChunk =
  block
    chunk_type = BEUInt32
    let len = BEUInt32 as uint 64
    payload = Many len UInt8

def Main =
  block
    Match [0x44, 0x50, 0x4B]
    version = UInt8
    num_chunks = BEUInt16
    chunks = Many num_chunks DataChunk
    END
