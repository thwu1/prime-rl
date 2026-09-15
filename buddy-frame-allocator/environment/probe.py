#!/usr/bin/env python3
"""Wrapper for interacting with the reference allocator binary.

Example:
    from probe import ReferenceAllocator
    ref = ReferenceAllocator()
    pfn = ref.alloc_pages(0, 1, 1)
    stats = ref.get_zone_stats(1)
    ref.free_pages(pfn, 0)
    ref.close()
"""
import subprocess


class ReferenceAllocator:
    def __init__(self, binary="/app/allocator_ref"):
        self._proc = subprocess.Popen(
            [binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def _send(self, cmd):
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()
        return self._proc.stdout.readline().strip()

    def alloc_pages(self, order, zone, migrate_type):
        return int(self._send(f"ALLOC {order} {zone} {migrate_type}"))

    def free_pages(self, pfn, order):
        r = self._send(f"FREE {pfn} {order}")
        if r != "OK":
            raise ValueError(r)

    def get_zone_stats(self, zone):
        line = self._send(f"STATS {zone}")
        parts = {}
        for token in line.split():
            k, v = token.split("=", 1)
            parts[k] = v
        return {
            "total_pages": int(parts["total_pages"]),
            "free_pages": int(parts["free_pages"]),
            "nr_free": [int(x) for x in parts["nr_free"].split(",")],
        }

    def get_allocation_info(self, pfn):
        line = self._send(f"INFO {pfn}")
        if line == "NONE":
            return None
        parts = {}
        for token in line.split():
            k, v = token.split("=", 1)
            parts[k] = v
        return {
            "allocated": bool(int(parts["allocated"])),
            "order": int(parts["order"]),
            "zone": int(parts["zone"]),
            "migrate_type": int(parts["migrate_type"]),
            "base_pfn": int(parts["base_pfn"]),
        }

    def compact_zone(self, zone):
        return int(self._send(f"COMPACT {zone}"))

    def fragmentation_index(self, zone, order):
        return float(self._send(f"FRAG {zone} {order}"))

    def close(self):
        try:
            self._proc.stdin.write("QUIT\n")
            self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
