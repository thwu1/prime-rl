-- Simple message container format

def Main =
  block
    Match [0x48, 0x44, 0x52]
    version = UInt8
    msg_count = BEUInt16
    messages = Many (msg_count as uint 64) Message
    END

def Message =
  block
    tag = UInt8 as? MsgTag
    len = UInt8 as uint 64
    payload = Many len UInt8

bitdata MsgTag where
  text    = 0x01 : uint 8
  binary  = 0x02
  control = 0x03
