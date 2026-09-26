#!/usr/bin/env python3
"""Verify a recovered Qwen tar stream without materializing its contents."""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path
from typing import BinaryIO

BLOCK_SIZE = 512
RECORD_SIZE = 10240


class CanonicalTarAuditor:
    """Incrementally require one canonical tar followed only by zero padding."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.payload_bytes = 0
        self.ended = False
        self.expected_total_bytes: int | None = None
        self.processed_bytes = 0
        self.total_bytes = 0
        self.zero_headers = 0

    @staticmethod
    def _number(field: bytes) -> int:
        if field[0] & 0x80:
            return int.from_bytes(field, "big") & ((1 << (len(field) * 8 - 1)) - 1)
        value = field.rstrip(b"\0 ").lstrip(b" ")
        return int(value or b"0", 8)

    @classmethod
    def _validate_header(cls, block: bytes) -> int:
        stored = cls._number(block[148:156])
        observed = sum(block[:148]) + (8 * ord(" ")) + sum(block[156:])
        if stored != observed:
            raise ValueError("invalid tar header")
        return cls._number(block[124:136])

    def feed(self, value: bytes) -> None:
        self.total_bytes += len(value)
        self.buffer.extend(value)
        while len(self.buffer) >= BLOCK_SIZE:
            block = bytes(self.buffer[:BLOCK_SIZE])
            del self.buffer[:BLOCK_SIZE]
            self.processed_bytes += BLOCK_SIZE
            if self.ended:
                if any(block):
                    raise ValueError("nonzero trailing tar data")
                continue
            if self.payload_bytes:
                payload_in_block = min(self.payload_bytes, BLOCK_SIZE)
                if payload_in_block < BLOCK_SIZE and any(block[payload_in_block:]):
                    raise ValueError("nonzero member padding")
                self.payload_bytes -= payload_in_block
                continue
            if not any(block):
                self.zero_headers += 1
                if self.zero_headers == 2:
                    self.ended = True
                    self.expected_total_bytes = ((self.processed_bytes + RECORD_SIZE - 1) // RECORD_SIZE) * RECORD_SIZE
                continue
            if self.zero_headers:
                raise ValueError("noncanonical tar terminator")
            self.payload_bytes = self._validate_header(block)

    def finish(self) -> None:
        if (
            self.buffer
            or self.payload_bytes
            or not self.ended
            or self.zero_headers < 2
            or self.expected_total_bytes is None
            or self.total_bytes != self.expected_total_bytes
        ):
            raise ValueError("incomplete or noncanonical tar stream")


class AuditedReader:
    def __init__(self, stream: BinaryIO, auditor: CanonicalTarAuditor) -> None:
        self.stream = stream
        self.auditor = auditor

    def read(self, size: int = -1) -> bytes:
        value = self.stream.read(size)
        self.auditor.feed(value)
        return value


def _fail() -> int:
    print("archive_member_validation_failed", file=sys.stderr)
    return 2


def _digest(stream: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(1024 * 1024):
        size += len(block)
        digest.update(block)
    return size, digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        return _fail()
    try:
        manifest = json.loads(Path(sys.argv[1]).read_bytes())
        members = manifest["archive"]["members"]
        if not isinstance(members, list) or len(members) != 7:
            return _fail()
        expected = [(member["name"], member["bytes"], member["sha256"]) for member in members]
        auditor = CanonicalTarAuditor()
        audited_stream = AuditedReader(sys.stdin.buffer, auditor)
        with tarfile.open(fileobj=audited_stream, mode="r|") as archive:
            observed = []
            for member in archive:
                if not (
                    member.isreg()
                    and member.linkname == ""
                    and member.mode == 0o600
                    and member.uid == 0
                    and member.gid == 0
                    and member.mtime == 0
                ):
                    return _fail()
                stream = archive.extractfile(member)
                if stream is None:
                    return _fail()
                size, digest = _digest(stream)
                observed.append((member.name, size, digest))
        while audited_stream.read(1024 * 1024):
            pass
        auditor.finish()
        if observed != expected:
            return _fail()
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, tarfile.TarError):
        return _fail()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
