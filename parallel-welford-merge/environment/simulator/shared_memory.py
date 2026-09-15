"""
Simulates GPU shared memory bank conflict detection.

Shared memory is organized into banks (typically 32 banks, each 4 bytes wide).
When multiple threads in a warp access different addresses that map to the same
bank, a bank conflict occurs, serializing the accesses.
"""


class SharedMemorySimulator:
    """Simulates shared memory bank conflict analysis."""

    def __init__(self, num_banks=32, bank_width_bytes=4):
        self.num_banks = num_banks
        self.bank_width = bank_width_bytes

    def get_bank(self, byte_address):
        """Determine which bank a byte address maps to.

        Each bank is bank_width bytes wide. Consecutive bank_width-byte words
        map to consecutive banks, wrapping around at num_banks.
        """
        return byte_address % self.num_banks

    def count_conflicts(self, byte_addresses):
        """Count bank conflicts for a set of simultaneous accesses.

        Args:
            byte_addresses: list of byte addresses accessed by threads in a warp

        Returns:
            Number of extra serialized accesses beyond the conflict-free minimum.
            0 means conflict-free.
        """
        bank_counts = {}
        for addr in byte_addresses:
            bank = self.get_bank(addr)
            bank_counts[bank] = bank_counts.get(bank, 0) + 1

        conflicts = sum(count - 1 for count in bank_counts.values() if count > 1)
        return conflicts

    def analyze_struct_layout(self, struct_size, field_offset, num_threads,
                               base_address=0):
        """Analyze bank conflicts when threads access a field within a struct array.

        In shared memory, an array of structs is laid out contiguously:
            thread i accesses byte address: base + i * struct_size + field_offset

        Args:
            struct_size: total bytes per struct
            field_offset: byte offset of the target field within the struct
            num_threads: number of threads (typically warp_size = 32)
            base_address: starting address of the struct array

        Returns:
            dict with conflict analysis results
        """
        addresses = []
        for tid in range(num_threads):
            addr = base_address + tid * struct_size + field_offset
            addresses.append(addr)

        conflicts = self.count_conflicts(addresses)
        banks_used = set(self.get_bank(a) for a in addresses)

        return {
            'field_offset': field_offset,
            'addresses_sample': addresses[:8],
            'banks_sample': [self.get_bank(a) for a in addresses[:8]],
            'total_conflicts': conflicts,
            'unique_banks': len(banks_used)
        }

    def find_optimal_padding(self, base_struct_size, field_offsets, num_threads,
                              max_padding=64):
        """Find minimum padding to eliminate all bank conflicts.

        Tries padding values from 0 to max_padding bytes, checking each
        field for conflicts. Returns the first conflict-free padding.

        Args:
            base_struct_size: original struct size in bytes
            field_offsets: list of byte offsets for each field
            num_threads: number of threads per warp
            max_padding: maximum padding to try

        Returns:
            dict with optimal padding result
        """
        for padding in range(0, max_padding + 1):
            padded_size = base_struct_size + padding
            all_conflict_free = True

            for offset in field_offsets:
                analysis = self.analyze_struct_layout(
                    padded_size, offset, num_threads)
                if analysis['total_conflicts'] > 0:
                    all_conflict_free = False
                    break

            if all_conflict_free:
                return {
                    'optimal_padding_bytes': padding,
                    'padded_struct_size_bytes': padded_size,
                    'conflicts_eliminated': True
                }

        return {
            'optimal_padding_bytes': -1,
            'padded_struct_size_bytes': base_struct_size + max_padding,
            'conflicts_eliminated': False
        }
