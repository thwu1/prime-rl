-- Sensor data archive format

def Main =
  block
    Match [0x53, 0x44]
    header = Header
    records = Many (header.count as uint 64) Record
    Match [0xFF, 0xFF]
    END

def Header =
  block
    version = UInt8
    flags = UInt8 as? Flags
    count = BEUInt16

bitdata Flags where
  Flags = { compressed : uint 1, signed : uint 1, reserved : uint 6 }

def Record =
  block
    sensor_id = BEUInt16
    reading = Reading

def Reading =
  First
    temperature = TempReading
    pressure = PressReading
    raw = RawReading

def TempReading =
  block
    Match [0x01]
    value = BEUInt16

def PressReading =
  block
    Match [0x02]
    value = BEUInt32

def RawReading =
  block
    Match [0x03]
    len = UInt8 as uint 64
    data = Many len UInt8
