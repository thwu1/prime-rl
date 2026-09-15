-- Format with backtracking alternatives via First
-- Magic: "CHO", then items that are either pairs or singles

def PairItem =
  block
    Match [0x02]
    first = UInt8
    second = UInt8

def SingleItem =
  block
    Match [0x01]
    value = UInt8

def Item =
  First
    pair = PairItem
    single = SingleItem

def Main =
  block
    Match [0x43, 0x48, 0x4F]
    items = Many Item
    END
