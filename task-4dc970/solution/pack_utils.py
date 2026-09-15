"""Binary serialization utilities for quantized tensors.

Handles packing and unpacking of 4-bit quantized indices into byte-level
storage, and checkpoint I/O for quantized weight tensors.
"""

import struct


def pack_nibbles(indices):
    """Pack a list of 4-bit indices (0-15) into bytes.

    Each byte stores two indices: the first index in the low nibble (bits 0-3)
    and the second index in the high nibble (bits 4-7).

    Args:
        indices: list of ints in [0, 15].

    Returns:
        bytes object with packed data.
    """
    packed = bytearray()
    for i in range(0, len(indices), 2):
        low = indices[i] & 0xF
        if i + 1 < len(indices):
            high = indices[i + 1] & 0xF
        else:
            high = 0
        packed.append(low | (high << 4))
    return bytes(packed)


def unpack_nibbles(data, count):
    """Unpack 4-bit indices from packed bytes.

    Reverses the packing performed by pack_nibbles: low nibble is the first
    index, high nibble is the second index.

    Args:
        data: bytes object with packed nibble data.
        count: number of indices to extract.

    Returns:
        list of ints in [0, 15].
    """
    indices = []
    for byte_val in data:
        lo = byte_val & 0xF
        hi = (byte_val >> 4) & 0xF
        indices.append(lo)
        indices.append(hi)
    return indices[:count]


def write_checkpoint(filepath, indices, absmax_values, blocksize):
    """Write quantized weights to a binary checkpoint file.

    Format:
        Header (16 bytes):
            - 4 bytes: magic "NF4Q"
            - 4 bytes: uint32 num_elements (little-endian)
            - 4 bytes: uint32 blocksize (little-endian)
            - 4 bytes: uint32 num_blocks (little-endian)
        Body:
            - num_blocks * 4 bytes: float32 absmax per block (little-endian)
            - ceil(num_elements / 2) bytes: packed 4-bit indices

    Args:
        filepath: path to write the checkpoint.
        indices: list of 4-bit index values.
        absmax_values: list of per-block absmax scaling factors.
        blocksize: quantization block size.
    """
    num_elements = len(indices)
    num_blocks = len(absmax_values)

    with open(filepath, 'wb') as f:
        f.write(b'NF4Q')
        f.write(struct.pack('<I', num_elements))
        f.write(struct.pack('<I', blocksize))
        f.write(struct.pack('<I', num_blocks))

        for am in absmax_values:
            f.write(struct.pack('<f', am))

        f.write(pack_nibbles(indices))


def read_checkpoint(filepath):
    """Read quantized weights from a binary checkpoint file.

    Args:
        filepath: path to the checkpoint file.

    Returns:
        dict with keys: indices, absmax, blocksize, num_elements.
    """
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != b'NF4Q':
            raise ValueError(f"Invalid checkpoint magic: {magic!r}")

        num_elements = struct.unpack('<I', f.read(4))[0]
        blocksize = struct.unpack('<I', f.read(4))[0]
        num_blocks = struct.unpack('<I', f.read(4))[0]

        absmax_values = []
        for _ in range(num_blocks):
            absmax_values.append(struct.unpack('<f', f.read(4))[0])

        packed_data = f.read()
        indices = unpack_nibbles(packed_data, num_elements)

    return {
        "indices": indices,
        "absmax": absmax_values,
        "blocksize": blocksize,
        "num_elements": num_elements,
    }
