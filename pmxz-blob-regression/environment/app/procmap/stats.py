
"""Compression statistics tracking for monitoring and tuning.

Tracks metrics about compression operations to help tune the
compression threshold and level parameters.
"""

import time


class CompressionStats:
    """Accumulates statistics about compression/decompression operations."""

    def __init__(self):
        self.total_compressions = 0
        self.total_decompressions = 0
        self.total_raw_bytes = 0
        self.total_compressed_bytes = 0
        self.compression_times = []
        self.decompression_times = []
        self.format_counts = {"raw": 0, "blob": 0}
        self.size_histogram = {}  # bucket -> count

    def record_compression(self, raw_size, compressed_size, elapsed_ms):
        """Record a compression operation.

        Args:
            raw_size: Size of uncompressed data in bytes
            compressed_size: Size of compressed output in bytes
            elapsed_ms: Time taken for compression in milliseconds
        """
        self.total_compressions += 1
        self.total_raw_bytes += raw_size
        self.total_compressed_bytes += compressed_size
        self.compression_times.append(elapsed_ms)

        bucket = (raw_size // 1024) * 1024
        self.size_histogram[bucket] = self.size_histogram.get(bucket, 0) + 1

    def record_decompression(self, compressed_size, raw_size, elapsed_ms):
        """Record a decompression operation.

        Args:
            compressed_size: Size of compressed input in bytes
            raw_size: Size of decompressed output in bytes
            elapsed_ms: Time taken for decompression in milliseconds
        """
        self.total_decompressions += 1
        self.decompression_times.append(elapsed_ms)

    def record_format(self, fmt):
        """Record which serialization format was used.

        Args:
            fmt: Format string ("raw" or "blob")
        """
        if fmt in self.format_counts:
            self.format_counts[fmt] += 1

    def get_average_ratio(self):
        """Get the average compression ratio (compressed/uncompressed).

        Returns:
            Float ratio, or 0.0 if no compressions recorded
        """
        if self.total_raw_bytes == 0:
            return 0.0
        return self.total_compressed_bytes / self.total_raw_bytes

    def get_summary(self):
        """Get a summary dictionary of all compression statistics.

        Returns:
            Dictionary with compression metrics
        """
        avg_comp_time = (
            sum(self.compression_times) / len(self.compression_times)
            if self.compression_times else 0.0
        )
        avg_decomp_time = (
            sum(self.decompression_times) / len(self.decompression_times)
            if self.decompression_times else 0.0
        )

        return {
            "total_compressions": self.total_compressions,
            "total_decompressions": self.total_decompressions,
            "average_compression_ratio": round(self.get_average_ratio(), 4),
            "average_compression_time_ms": round(avg_comp_time, 3),
            "average_decompression_time_ms": round(avg_decomp_time, 3),
            "format_distribution": dict(self.format_counts),
            "total_raw_bytes": self.total_raw_bytes,
            "total_compressed_bytes": self.total_compressed_bytes,
        }


# Global stats instance
_global_stats = CompressionStats()


def get_global_stats():
    """Get the global compression statistics instance."""
    return _global_stats


def reset_global_stats():
    """Reset global compression statistics."""
    global _global_stats
    _global_stats = CompressionStats()
