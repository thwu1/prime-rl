#!/usr/bin/env python3
"""Generate forensic data for BitTorrent reconstruction task."""
import hashlib
import os
import random
import struct

SEED = 20240801
PIECE_LENGTH = 2048


def bencode_encode(obj):
    if isinstance(obj, int):
        return "i{}e".format(obj).encode("ascii")
    elif isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    elif isinstance(obj, list):
        return b"l" + b"".join(bencode_encode(item) for item in obj) + b"e"
    elif isinstance(obj, dict):
        result = b"d"
        for key, value in sorted(obj.items(), key=lambda x: x[0]):
            assert isinstance(key, bytes)
            result += bencode_encode(key) + bencode_encode(value)
        result += b"e"
        return result
    raise TypeError("Cannot bencode {}".format(type(obj)))


def write_piece_file(path, index, data):
    with open(path, "wb") as f:
        f.write(struct.pack(">I", index))
        f.write(data)


def write_bt_message(f, msg_id, payload):
    length = 1 + len(payload)
    f.write(struct.pack(">I", length))
    f.write(struct.pack("B", msg_id))
    f.write(payload)


def write_keepalive(f):
    f.write(struct.pack(">I", 0))


def write_piece_message(f, piece_index, begin, block_data):
    payload = struct.pack(">II", piece_index, begin) + block_data
    write_bt_message(f, 7, payload)


def write_have_message(f, piece_index):
    payload = struct.pack(">I", piece_index)
    write_bt_message(f, 4, payload)


def write_bitfield_message(f, bitfield_bytes):
    write_bt_message(f, 5, bitfield_bytes)


def write_interested_message(f):
    write_bt_message(f, 2, b"")


def write_unchoke_message(f):
    write_bt_message(f, 1, b"")


def main():
    rng = random.Random(SEED)

    file_specs = [
        ("src/main.c", 2500),
        ("src/util.h", 800),
        ("src/parser/lexer.c", 3200),
        ("src/parser/tokens.dat", 450),
        ("docs/README.txt", 1800),
        ("docs/api_reference.md", 4100),
        ("build/Makefile", 600),
        ("build/config.ini", 280),
        ("assets/icon.bin", 1500),
        ("assets/font.dat", 2200),
    ]

    file_contents = {}
    for path, size in file_specs:
        if path.endswith(".bin") or path.endswith(".dat"):
            content = bytes([rng.randint(0, 255) for _ in range(size)])
        else:
            content = bytes([rng.randint(32, 126) for _ in range(size)])
        file_contents[path] = content

    concat = b"".join(file_contents[p] for p, _ in file_specs)
    total_size = len(concat)

    pieces_data = []
    piece_hashes_raw = b""
    for i in range(0, total_size, PIECE_LENGTH):
        piece = concat[i:i + PIECE_LENGTH]
        pieces_data.append(piece)
        piece_hashes_raw += hashlib.sha1(piece).digest()

    num_pieces = len(pieces_data)

    files_list = []
    for path, _ in file_specs:
        parts = path.split("/")
        files_list.append({
            b"length": len(file_contents[path]),
            b"path": [p.encode() for p in parts],
        })

    info_dict = {
        b"files": files_list,
        b"name": b"dataset",
        b"piece length": PIECE_LENGTH,
        b"pieces": piece_hashes_raw,
    }

    metainfo = {
        b"announce": b"http://tracker.example.com/announce",
        b"comment": b"dataset archive v2",
        b"created by": b"torrent-tool/1.4.2",
        b"creation date": 1706745600,
        b"info": info_dict,
    }

    os.makedirs("/opt/task_data/pieces", exist_ok=True)

    with open("/opt/task_data/metadata.torrent", "wb") as f:
        f.write(bencode_encode(metainfo))

    # Piece 0: valid, in pieces/
    write_piece_file("/opt/task_data/pieces/a1b2c3.bin", 0, pieces_data[0])

    # Piece 1: corrupted, in pieces/
    corrupted = bytearray(pieces_data[1])
    corrupted[50] ^= 0xFF
    corrupted[500] ^= 0xFF
    corrupted[1000] ^= 0xFF
    corrupted[1500] ^= 0xFF
    corrupted[2000] ^= 0xFF
    write_piece_file("/opt/task_data/pieces/d4e5f6.bin", 1, bytes(corrupted))

    # Piece 3: valid, in pieces/
    write_piece_file("/opt/task_data/pieces/g7h8i9.bin", 3, pieces_data[3])

    # Piece 6: duplicate — two files, one valid one corrupted
    write_piece_file("/opt/task_data/pieces/j0k1l2.bin", 6, pieces_data[6])
    corrupted_6 = bytearray(pieces_data[6])
    corrupted_6[100] ^= 0xFF
    write_piece_file("/opt/task_data/pieces/m3n4o5.bin", 6, bytes(corrupted_6))

    # Piece 7: valid, in pieces/
    write_piece_file("/opt/task_data/pieces/p6q7r8.bin", 7, pieces_data[7])

    # Red herrings
    write_piece_file("/opt/task_data/pieces/z9z9z9.bin", 42, b"\xde\xad" * 100)
    with open("/opt/task_data/pieces/manifest.txt", "w") as f:
        f.write("Downloaded piece cache.\n")
    write_piece_file("/opt/task_data/pieces/xx00yy.bin", 99, b"\x00" * 150)

    # Peer traffic log: concatenated BitTorrent peer wire protocol messages
    with open("/opt/task_data/peer_traffic.log", "wb") as f:
        write_keepalive(f)
        write_bitfield_message(f, b"\xff\x80")
        write_interested_message(f)
        write_unchoke_message(f)
        write_have_message(f, 0)

        # Piece 2: full piece in one message
        write_piece_message(f, 2, 0, pieces_data[2])

        write_have_message(f, 3)
        write_keepalive(f)

        # Piece 5: split into two blocks (1024 bytes each)
        write_piece_message(f, 5, 0, pieces_data[5][:1024])
        write_have_message(f, 6)
        write_piece_message(f, 5, 1024, pieces_data[5][1024:])

        write_keepalive(f)
        write_have_message(f, 7)

        # Piece 8: last piece (shorter than piece_length)
        write_piece_message(f, 8, 0, pieces_data[8])

        write_keepalive(f)

    assert os.path.isfile("/opt/task_data/metadata.torrent")
    assert os.path.isdir("/opt/task_data/pieces")
    assert os.path.isfile("/opt/task_data/peer_traffic.log")

    bin_files = [fn for fn in os.listdir("/opt/task_data/pieces") if fn.endswith(".bin")]
    assert len(bin_files) == 8

    info_hash = hashlib.sha1(bencode_encode(info_dict)).hexdigest()
    print("Setup complete: {} pieces, {} bytes, hash={}".format(
        num_pieces, total_size, info_hash))


if __name__ == "__main__":
    main()
