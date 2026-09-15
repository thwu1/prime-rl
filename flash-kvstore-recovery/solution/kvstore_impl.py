"""
FlashKVStore — Crash-consistent key-value store for simulated NOR flash memory.
Implements the TKV1 on-flash format with crash-safe compaction and wear-leveling.
"""

import struct
import zlib

# On-flash format constants
PAGE_MAGIC = b'\x54\x4b\x56\x31'  # "TKV1"
ENTRY_MAGIC = b'\xae\x73'
PAGE_HEADER_SIZE = 12
ENTRY_HEADER_SIZE = 16

PAGE_STATUS_ERASED = 0xFF
PAGE_STATUS_ACTIVE = 0x0F
PAGE_STATUS_FULL = 0x00

ENTRY_STATE_VALID = 0x0F
ENTRY_STATE_INVALID = 0x00


def fnv1a_32(data: bytes) -> int:
    """Compute FNV-1a 32-bit hash."""
    h = 0x811c9dc5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def compute_entry_crc(key_len: int, value_len: int, key_hash: int,
                      key: bytes, value: bytes) -> int:
    """
    Compute CRC32 for an entry.

    Covers: key_len (1 B) + value_len (4 B LE) + key_hash (4 B LE) + key + value.
    The state byte is intentionally excluded so that invalidation
    (state 0x0F -> 0x00) does not break the checksum.
    """
    crc_data = struct.pack('<BII', key_len, value_len, key_hash) + key + value
    return zlib.crc32(crc_data) & 0xFFFFFFFF


class FlashKVStore:
    """Crash-consistent key-value store on simulated NOR flash."""

    def __init__(self, flash):
        self.flash = flash
        self.page_size = flash.page_size
        self.num_pages = flash.num_pages
        self._index = {}          # key (bytes) -> value (bytes)
        self._entry_locs = {}     # key (bytes) -> (page_num, offset_in_page)
        self._active_page = None
        self._next_seq = 0
        self._write_offsets = {}  # page_num -> next byte offset within page
        self._page_seqs = {}      # page_num -> sequence number
        self._scan()

    # ------------------------------------------------------------------
    # Internal: scan / rebuild
    # ------------------------------------------------------------------

    def _scan(self):
        """Scan flash and rebuild in-memory index (crash recovery)."""
        self._index.clear()
        self._entry_locs.clear()
        self._active_page = None
        self._next_seq = 0
        self._write_offsets.clear()
        self._page_seqs.clear()

        # Pass 1: identify initialized pages and restore erase counts
        page_info = {}
        for pn in range(self.num_pages):
            base = pn * self.page_size
            magic = self.flash.read(base, 4)
            if magic != PAGE_MAGIC:
                continue
            raw = self.flash.read(base + 4, 8)
            status = raw[0]
            if status == PAGE_STATUS_ERASED:
                continue
            seq_num = struct.unpack_from('<H', raw, 1)[0]
            erase_count = struct.unpack_from('<I', raw, 4)[0]
            page_info[pn] = (seq_num, status)
            self._page_seqs[pn] = seq_num
            # Restore erase counts from page headers so wear-leveling
            # decisions survive power cycles
            self.flash.erase_counts[pn] = erase_count
            if seq_num >= self._next_seq:
                self._next_seq = seq_num + 1

        # Process pages in ascending sequence order
        sorted_pages = sorted(page_info, key=lambda p: page_info[p][0])

        for pn in sorted_pages:
            seq_num, status = page_info[pn]
            base = pn * self.page_size
            offset = PAGE_HEADER_SIZE

            while offset + ENTRY_HEADER_SIZE <= self.page_size:
                abs_off = base + offset
                header = self.flash.read(abs_off, ENTRY_HEADER_SIZE)

                if header[0:2] != ENTRY_MAGIC:
                    break

                state = header[2]
                key_len = header[3]
                if key_len == 0:
                    break

                value_len = struct.unpack_from('<I', header, 4)[0]
                key_hash = struct.unpack_from('<I', header, 8)[0]
                stored_crc = struct.unpack_from('<I', header, 12)[0]

                total = ENTRY_HEADER_SIZE + key_len + value_len
                if offset + total > self.page_size:
                    break

                key = self.flash.read(abs_off + ENTRY_HEADER_SIZE, key_len)
                value = self.flash.read(
                    abs_off + ENTRY_HEADER_SIZE + key_len, value_len
                )

                computed_crc = compute_entry_crc(
                    key_len, value_len, key_hash, key, value
                )
                if computed_crc != stored_crc:
                    break  # stop scanning this page on CRC failure

                if state == ENTRY_STATE_VALID:
                    self._index[key] = value
                    self._entry_locs[key] = (pn, offset)
                elif state == ENTRY_STATE_INVALID:
                    self._index.pop(key, None)
                    self._entry_locs.pop(key, None)

                offset += total

            self._write_offsets[pn] = offset
            if status == PAGE_STATUS_ACTIVE:
                self._active_page = pn

    # ------------------------------------------------------------------
    # Internal: page helpers
    # ------------------------------------------------------------------

    def _write_page_header(self, page_num, seq_num, status, erase_count):
        base = page_num * self.page_size
        header = (
            PAGE_MAGIC
            + bytes([status])
            + struct.pack('<H', seq_num)
            + b'\xff'
            + struct.pack('<I', erase_count)
        )
        self.flash.write(base, header)

    def _activate_next_page(self):
        """Mark current active page as full; activate the free page
        with the lowest erase count (wear-leveling)."""
        if self._active_page is not None:
            state_off = self._active_page * self.page_size + 4
            self.flash.write(state_off, bytes([PAGE_STATUS_FULL]))

        # Find all free (erased) pages
        candidates = []
        for pn in range(self.num_pages):
            base = pn * self.page_size
            if self.flash.read(base, 1) == b'\xff':
                candidates.append((self.flash.erase_counts[pn], pn))

        if not candidates:
            self._active_page = None
            return None

        # Pick the page with the lowest erase count (wear-leveling)
        candidates.sort()
        _, pn = candidates[0]

        seq = self._next_seq
        self._next_seq += 1
        ec = self.flash.erase_counts[pn]
        self._write_page_header(pn, seq, PAGE_STATUS_ACTIVE, ec)
        self._active_page = pn
        self._write_offsets[pn] = PAGE_HEADER_SIZE
        self._page_seqs[pn] = seq
        return pn

    def _is_initialized_page(self, pn):
        """Check if page has a valid TKV1 header and is active or full."""
        base = pn * self.page_size
        if self.flash.read(base, 4) != PAGE_MAGIC:
            return False
        status = self.flash.read(base + 4, 1)[0]
        return status in (PAGE_STATUS_ACTIVE, PAGE_STATUS_FULL)

    def _page_has_dead_entries(self, pn):
        """Scan page for any invalidated entries."""
        base = pn * self.page_size
        offset = PAGE_HEADER_SIZE
        while offset + ENTRY_HEADER_SIZE <= self.page_size:
            hdr = self.flash.read(base + offset, ENTRY_HEADER_SIZE)
            if hdr[0:2] != ENTRY_MAGIC:
                break
            key_len = hdr[3]
            if key_len == 0:
                break
            value_len = struct.unpack_from('<I', hdr, 4)[0]
            total = ENTRY_HEADER_SIZE + key_len + value_len
            if offset + total > self.page_size:
                break
            if hdr[2] == ENTRY_STATE_INVALID:
                return True
            offset += total
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(self):
        """Erase all pages and initialise page 0 as active."""
        for i in range(self.num_pages):
            self.flash.erase_page(i)
        ec = self.flash.erase_counts[0]
        self._write_page_header(0, 0, PAGE_STATUS_ACTIVE, ec)
        self._active_page = 0
        self._next_seq = 1
        self._write_offsets = {0: PAGE_HEADER_SIZE}
        self._page_seqs = {0: 0}
        self._index.clear()
        self._entry_locs.clear()

    def put(self, key: bytes, value: bytes) -> bool:
        """Store *key* -> *value*. Returns False if flash is full.

        Uses write-before-invalidate ordering for crash safety:
        the new entry is written first, then the old entry is invalidated.
        If power fails between the two writes, both copies exist as valid
        entries and recovery picks the newer one (higher page sequence / offset).
        """
        if not isinstance(key, bytes) or not isinstance(value, bytes):
            raise TypeError("key and value must be bytes")
        if len(key) == 0 or len(key) > 255:
            raise ValueError("key length must be 1-255")

        total = ENTRY_HEADER_SIZE + len(key) + len(value)
        if total > self.page_size - PAGE_HEADER_SIZE:
            raise ValueError("entry too large for a single page")

        # Ensure active page has space
        if self._active_page is not None:
            wo = self._write_offsets.get(self._active_page, PAGE_HEADER_SIZE)
            if wo + total > self.page_size:
                if self._activate_next_page() is None:
                    return False
        else:
            if self._activate_next_page() is None:
                return False

        # Save old location before any changes
        old_loc = self._entry_locs.get(key)

        # Build and write new entry FIRST (crash-safe ordering)
        key_hash = fnv1a_32(key)
        crc = compute_entry_crc(len(key), len(value), key_hash, key, value)
        entry = (
            ENTRY_MAGIC
            + bytes([ENTRY_STATE_VALID])
            + bytes([len(key)])
            + struct.pack('<III', len(value), key_hash, crc)
            + key
            + value
        )

        wo = self._write_offsets[self._active_page]
        abs_off = self._active_page * self.page_size + wo
        self.flash.write(abs_off, entry)

        # Update in-memory index
        self._index[key] = value
        self._entry_locs[key] = (self._active_page, wo)
        self._write_offsets[self._active_page] = wo + total

        # THEN invalidate old entry (crash-safe: new entry already persisted)
        if old_loc is not None:
            old_pn, old_off = old_loc
            abs_state = old_pn * self.page_size + old_off + 2
            self.flash.write(abs_state, bytes([ENTRY_STATE_INVALID]))

        return True

    def get(self, key: bytes):
        """Return value for *key*, or ``None``."""
        return self._index.get(key)

    def delete(self, key: bytes) -> bool:
        """Invalidate entry for *key*. Returns True if key existed."""
        if key not in self._entry_locs:
            return False
        old_pn, old_off = self._entry_locs[key]
        abs_state = old_pn * self.page_size + old_off + 2
        self.flash.write(abs_state, bytes([ENTRY_STATE_INVALID]))
        del self._index[key]
        del self._entry_locs[key]
        return True

    def compact(self):
        """Crash-safe compaction with wear-leveling.

        Invariant: every live key-value pair exists on at least one valid
        page at all times. Entries are copied to new pages before source
        pages are erased.

        Algorithm:
        1. Identify non-active initialized pages with data.
        2. For each: migrate entries whose current location is on that page
           to the active page (via put()), then erase the source page.
        3. Handle the active page: if it has dead entries, switch to a new
           active page, migrate live entries, then erase the old one.
        """
        # Snapshot pages to consider (excluding free pages)
        compactable = []
        for pn in range(self.num_pages):
            if pn == self._active_page:
                continue
            if self._is_initialized_page(pn):
                compactable.append(pn)

        # Phase 1: Compact non-active pages
        for pn in compactable:
            # Re-check — page may have been reused during this loop
            if pn == self._active_page:
                continue
            if not self._is_initialized_page(pn):
                continue

            # Find entries whose CURRENT location is on this page
            entries_here = [(k, self._index[k])
                            for k in list(self._entry_locs)
                            if self._entry_locs[k][0] == pn]

            # Copy live entries to active page (put handles page switching)
            for k, v in entries_here:
                self.put(k, v)

            # All live entries have been migrated; safe to erase
            self.flash.erase_page(pn)

        # Phase 2: Handle the active page if it has dead entries
        if self._active_page is not None:
            ap = self._active_page
            if self._page_has_dead_entries(ap):
                saved = [(k, self._index[k])
                         for k in list(self._entry_locs)
                         if self._entry_locs[k][0] == ap]

                # Switch to a new active page (picks lowest EC)
                if self._activate_next_page() is not None:
                    for k, v in saved:
                        self.put(k, v)
                    self.flash.erase_page(ap)

    def list_keys(self):
        """Return list of all valid keys."""
        return list(self._index.keys())
