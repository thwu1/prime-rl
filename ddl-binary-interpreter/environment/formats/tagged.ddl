-- Tagged record format
-- Magic: "TG", then records with type-dispatched payloads

def Record =
  block
    let tag = UInt8
    data = case tag of
      1 -> {| byte_rec = UInt8 |}
      2 -> {| short_rec = BEUInt16 |}
      3 -> {| int_rec = BEUInt32 |}

def Main =
  block
    Match [0x54, 0x47]
    records = Many Record
    END
