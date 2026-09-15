"""Reed-Solomon Encoding and Decoding over GF(2^8).

"""

from galois import gf, gf_matrix_inv


def make_encoding_matrix(k, m):
    """Build a (k+m) x k encoding matrix for RS(k, m)."""
    matrix = []
    for i in range(k):
        matrix.append([1 if i == j else 0 for j in range(k)])
    for i in range(m):
        row = []
        for j in range(k):
            row.append(gf.inv(gf.add(i, m + j)))
        matrix.append(row)
    return matrix


def encode(data: bytes, k: int, m: int) -> list:
    """Encode *data* into k+m shards. Returns list of bytes objects."""
    shard_size = (len(data) + k - 1) // k
    padded = data + b'\x00' * (shard_size * k - len(data))

    data_shards = [padded[i * shard_size:(i + 1) * shard_size]
                   for i in range(k)]

    enc = make_encoding_matrix(k, m)
    parity_rows = enc[k:]

    parity_shards = []
    for i in range(m):
        buf = bytearray(shard_size)
        for pos in range(shard_size):
            v = 0
            for j in range(k):
                v ^= gf.mul(parity_rows[i][j], data_shards[j][pos])
            buf[pos] = v
        parity_shards.append(bytes(buf))

    return data_shards + parity_shards


def decode(shards: list, k: int, m: int, shard_indices: list) -> list:
    """Recover the k original data shards from any k available shards.

    Args:
        shards:        list of >= k shard byte-strings
        k, m:          RS parameters
        shard_indices: which rows of the encoding matrix these correspond to

    Returns list of k bytes objects (the recovered data shards).
    """
    if len(shards) < k or len(shard_indices) < k:
        raise ValueError(f"need >= {k} shards for recovery, got {len(shards)}")

    used = shards[:k]
    idx = shard_indices[:k]
    shard_size = len(used[0])

    enc = make_encoding_matrix(k, m)
    sub = [enc[i] for i in idx]
    inv = gf_matrix_inv(sub)

    result = []
    for i in range(k):
        buf = bytearray(shard_size)
        for pos in range(shard_size):
            v = 0
            for j in range(k):
                v ^= gf.mul(inv[i][j], used[j][pos])
            buf[pos] = v
        result.append(bytes(buf))
    return result
