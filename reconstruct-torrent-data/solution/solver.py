#!/usr/bin/env python3
"""Solve the BitTorrent forensic reconstruction task."""

import hashlib
import json
import os
import struct


class BencodeDecoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def _decode(self):
        ch = self.data[self.pos:self.pos + 1]
        if ch == b"i":
            return self._decode_int()
        elif ch == b"l":
            return self._decode_list()
        elif ch == b"d":
            return self._decode_dict()
        elif ch.isdigit():
            return self._decode_bytes()
        else:
            raise ValueError("Invalid bencode at pos {}".format(self.pos))

    def _decode_int(self):
        self.pos += 1
        end = self.data.index(b"e", self.pos)
        value = int(self.data[self.pos:end])
        self.pos = end + 1
        return value

    def _decode_bytes(self):
        colon = self.data.index(b":", self.pos)
        length = int(self.data[self.pos:colon])
        self.pos = colon + 1
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value

    def _decode_list(self):
        self.pos += 1
        result = []
        while self.data[self.pos:self.pos + 1] != b"e":
            result.append(self._decode())
        self.pos += 1
        return result

    def _decode_dict(self):
        self.pos += 1
        result = {}
        while self.data[self.pos:self.pos + 1] != b"e":
            key = self._decode_bytes()
            value = self._decode()
            result[key] = value
        self.pos += 1
        return result

    def decode_with_raw_info(self):
        assert self.data[self.pos:self.pos + 1] == b"d"
        self.pos += 1
        result = {}
        info_raw = None
        while self.data[self.pos:self.pos + 1] != b"e":
            key = self._decode_bytes()
            if key == b"info":
                info_start = self.pos
                value = self._decode()
                info_end = self.pos
                info_raw = self.data[info_start:info_end]
            else:
                value = self._decode()
            result[key] = value
        self.pos += 1
        return result, info_raw


def parse_peer_traffic(filepath, num_pieces):
    """Parse BitTorrent peer wire protocol messages from binary stream."""
    piece_blocks = {}

    with open(filepath, "rb") as f:
        data = f.read()

    pos = 0
    while pos + 4 <= len(data):
        msg_len = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4

        if msg_len == 0:
            continue

        if pos + msg_len > len(data):
            break

        msg_id = data[pos]
        payload = data[pos + 1:pos + msg_len]
        pos += msg_len

        if msg_id != 7:
            continue

        if len(payload) < 8:
            continue

        piece_idx = struct.unpack(">I", payload[0:4])[0]
        begin = struct.unpack(">I", payload[4:8])[0]
        block = payload[8:]

        if piece_idx >= num_pieces:
            continue

        if piece_idx not in piece_blocks:
            piece_blocks[piece_idx] = {}
        piece_blocks[piece_idx][begin] = block

    result = {}
    for idx, blocks in piece_blocks.items():
        sorted_offsets = sorted(blocks.keys())
        piece_data = b""
        for offset in sorted_offsets:
            if offset != len(piece_data):
                break
            piece_data += blocks[offset]

        h = hashlib.sha1(piece_data).digest()
        result[idx] = (h, piece_data)

    return result


def main():
    torrent_path = "/opt/task_data/metadata.torrent"
    pieces_dir = "/opt/task_data/pieces"
    traffic_path = "/opt/task_data/peer_traffic.log"
    output_dir = "/app/output"

    with open(torrent_path, "rb") as f:
        torrent_data = f.read()

    decoder = BencodeDecoder(torrent_data)
    metainfo, info_raw = decoder.decode_with_raw_info()

    info = metainfo[b"info"]
    piece_length = info[b"piece length"]
    pieces_hash_blob = info[b"pieces"]
    files_info = info[b"files"]
    torrent_name = info[b"name"].decode("utf-8")

    num_pieces = len(pieces_hash_blob) // 20
    expected_hashes = []
    for i in range(num_pieces):
        expected_hashes.append(pieces_hash_blob[i * 20:(i + 1) * 20])

    info_hash = hashlib.sha1(info_raw).hexdigest()
    total_size = sum(f[b"length"] for f in files_info)

    piece_candidates = {}
    for fname in os.listdir(pieces_dir):
        fpath = os.path.join(pieces_dir, fname)
        if not os.path.isfile(fpath) or not fname.endswith(".bin"):
            continue
        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            if len(raw) < 4:
                continue
            idx = struct.unpack(">I", raw[:4])[0]
            data = raw[4:]
            if idx >= num_pieces:
                continue
            h = hashlib.sha1(data).digest()
            if idx not in piece_candidates:
                piece_candidates[idx] = []
            piece_candidates[idx].append((h, data))
        except Exception:
            continue

    traffic_pieces = parse_peer_traffic(traffic_path, num_pieces)
    for idx, (h, data) in traffic_pieces.items():
        if idx not in piece_candidates:
            piece_candidates[idx] = []
        piece_candidates[idx].append((h, data))

    pieces_report = []
    valid_pieces = {}

    for i in range(num_pieces):
        expected = expected_hashes[i]
        if i not in piece_candidates:
            pieces_report.append({"index": i, "status": "missing"})
            continue

        candidates = piece_candidates[i]
        found_valid = False
        first_bad_hash = None

        for h, data in candidates:
            if h == expected:
                valid_pieces[i] = data
                entry = {"index": i, "status": "valid", "hash": expected.hex()}
                if len(candidates) > 1:
                    entry["duplicates_found"] = len(candidates)
                pieces_report.append(entry)
                found_valid = True
                break
            if first_bad_hash is None:
                first_bad_hash = h

        if not found_valid:
            pieces_report.append({
                "index": i,
                "status": "corrupted",
                "expected_hash": expected.hex(),
                "actual_hash": first_bad_hash.hex() if first_bad_hash else "",
            })

    pieces_report.sort(key=lambda x: x["index"])

    file_reports = []
    concat_offset = 0

    for file_entry in files_info:
        file_length = file_entry[b"length"]
        file_path_parts = [p.decode("utf-8") for p in file_entry[b"path"]]
        file_path = "/".join(file_path_parts)

        file_start = concat_offset
        file_end = concat_offset + file_length

        first_piece = file_start // piece_length
        last_piece = (file_end - 1) // piece_length if file_end > file_start \
            else first_piece
        all_valid = all(
            p in valid_pieces for p in range(first_piece, last_piece + 1))
        status = "complete" if all_valid else "partial"

        file_reports.append({
            "path": file_path, "length": file_length, "status": status})

        file_data = bytearray(file_length)

        for pidx in range(first_piece, last_piece + 1):
            if pidx not in valid_pieces:
                continue
            pdata = valid_pieces[pidx]
            pstart = pidx * piece_length
            pend = pstart + len(pdata)

            overlap_start = max(file_start, pstart)
            overlap_end = min(file_end, pend)
            if overlap_start >= overlap_end:
                continue

            piece_offset = overlap_start - pstart
            file_offset = overlap_start - file_start
            length = overlap_end - overlap_start
            file_data[file_offset:file_offset + length] = \
                pdata[piece_offset:piece_offset + length]

        out_path = os.path.join(output_dir, "files", torrent_name, file_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(file_data)

        concat_offset += file_length

    report = {
        "info_hash": info_hash,
        "piece_length": piece_length,
        "total_pieces": num_pieces,
        "total_size": total_size,
        "pieces": pieces_report,
        "files": file_reports,
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("Reconstruction complete.")
    print("Info hash: {}".format(info_hash))
    print("Pieces: {} total, {} verified".format(
        num_pieces, len(valid_pieces)))


if __name__ == "__main__":
    main()
