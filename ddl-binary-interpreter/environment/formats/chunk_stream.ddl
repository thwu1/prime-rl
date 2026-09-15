-- Format with bounded sub-stream parsing via Chunk
-- Magic: "CS", then frames with size-delimited content

def FrameContent =
  block
    frame_type = UInt8
    data = Many UInt8
    END

def Frame =
  block
    let size = BEUInt16 as uint 64
    content = Chunk size FrameContent

def Main =
  block
    Match [0x43, 0x53]
    frames = Many Frame
    END
