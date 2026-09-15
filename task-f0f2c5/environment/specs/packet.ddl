-- Network packet format with parameterized parsers

def Main =
  block
    Match [0x50, 0x4B]
    version = UInt8
    ptype = UInt8
    body = Body ptype
    checksum = BEUInt16
    END

def Body (ptype : uint 8) =
  case ptype of
    0x01 -> {| text = TextBody |}
    0x02 -> {| pairs = PairsBody |}
    _    -> {| raw = RawBody |}

def TextBody =
  block
    $$ = Many $[0x20 .. 0x7E]
    $[0x00]

def PairsBody =
  block
    count = UInt8 as uint 64
    items = Many count Pair

def Pair =
  block
    key = NullStr
    value = BEUInt16

def NullStr =
  block
    $$ = Many $[0x01 .. 0xFF]
    $[0x00]

def RawBody =
  block
    len = BEUInt16 as uint 64
    data = Many len UInt8
