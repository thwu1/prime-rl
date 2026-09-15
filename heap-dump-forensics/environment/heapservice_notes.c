/*
 * HeapService v2.4.1 - Forensic Recovery Notes
 * =============================================
 *
 * SYSTEM CONFIGURATION:
 *   Binary: /app/heapservice (stripped ELF, PIE-enabled)
 *   Runtime: glibc 2.39, x86-64, Ubuntu 24.04
 *   ASLR was disabled during forensic capture
 *   Heap base address: 0x55555555a000
 *   Dump coverage: 0x600 bytes from heap base per snapshot
 *
 * HEAP STRUCTURE:
 *   The service manages 8 heap slots (indices 0-7), allocated sequentially
 *   via calloc(). Slot allocation sizes can be determined by reverse-engineering
 *   the binary (check the SLOT_SIZES array in .rodata, or trace calloc calls
 *   in the disassembly).
 *
 *   The first heap chunk is always glibc's tcache_perthread_struct (0x290 bytes).
 *   User chunks follow immediately after. Each chunk has a 16-byte header
 *   (prev_size + size fields), and user data begins at chunk_address + 0x10.
 *
 *   Chunk size = ((malloc_request + 8 + 15) & ~15) on x86-64.
 *   tcache bin index = (chunk_size - 0x20) / 0x10.
 *
 * ENCRYPTED SESSION TOKEN:
 *   One of the slots contains an encrypted session token. The encryption uses:
 *     key = SHA-256(AUDIT_KEY || slot_userdata_virtual_address_as_LE_uint64)
 *   The plaintext is padded to 0x40 bytes with null bytes, then XOR'd
 *   cyclically with the 32-byte SHA-256 key.
 *
 *   AUDIT_KEY: 16-byte constant in the binary's .rodata section, stored in a
 *   packed struct immediately after the marker string "AUDIT_KEY_MATERIAL:".
 *   The key bytes begin at byte offset +20 from the marker string start
 *   (the marker occupies char[20] including null terminator).
 *
 *   The slot_userdata_virtual_address is the address the attacker targeted
 *   via tcache poisoning. Recover it from the corrupted tcache fd pointer.
 *
 * INCIDENT SUMMARY:
 *   An attacker exploited a heap overflow to corrupt a freed chunk's tcache
 *   fd pointer, redirecting the tcache chain to an unrelated heap slot.
 *   Two snapshots were captured:
 *
 *     /app/snapshot_clean.bin   - pre-attack (all slots allocated, tcache empty)
 *     /app/snapshot_attacked.bin - post-corruption (multiple frees, one poisoned fd)
 *
 *   Some frees in the attacked snapshot are legitimate service operations
 *   (the service periodically frees and reallocates buffers). Others are
 *   part of the attack. Distinguish them by analyzing tcache chain integrity.
 *
 *   The attack was detected before the attacker could consume the poisoned
 *   tcache entry, so the corruption is preserved in the attacked snapshot.
 *   The encrypted token data is unchanged between snapshots.
 *
 * TCACHE FORENSICS (glibc 2.34+ safe-linking):
 *   When freed to tcache, a chunk's user data region stores:
 *     offset +0: mangled fd pointer (next entry in tcache list)
 *     offset +8: tcache_key (address of tcache_perthread_struct user data)
 *
 *   The fd pointer is mangled using PROTECT_PTR:
 *     stored_fd = (pos >> 12) ^ actual_next_pointer
 *   where pos = virtual address of the fd field (= chunk user data address).
 *
 *   To recover the actual pointer:
 *     actual_next_pointer = (pos >> 12) ^ stored_fd
 *
 *   A tail entry (last in the list) has actual_next_pointer = 0 (NULL).
 *   A poisoned fd will de-mangle to an address that does NOT correspond
 *   to another freed chunk in the same tcache bin.
 *
 *   tcache_perthread_struct layout (at heap_base + 0x10):
 *     counts[64]: uint16_t array at offset 0 (128 bytes)
 *     entries[64]: pointer array at offset 0x80 (512 bytes)
 *     tcache bin index for a given chunk_size: (chunk_size - 0x20) / 0x10
 *
 */
