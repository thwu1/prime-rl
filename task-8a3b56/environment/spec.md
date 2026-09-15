# NF4 Quantization Library — Technical Reference

## Blockwise Quantization

Neural network weight tensors are quantized in contiguous blocks of `blocksize`
elements. Each block is independently scaled by its absolute maximum value,
normalizing all block elements into [-1, 1]. The normalized values are mapped
to their nearest quantization level in the codebook. Dequantization reverses
the process by looking up codebook values and rescaling.

## NF4 (NormalFloat4) Data Type

Pretrained neural network weights follow an approximately zero-centered normal
distribution. The NF4 data type exploits this statistical property by placing its
quantization levels at positions derived from the standard normal distribution
N(0, 1), such that each quantization bin captures approximately equal probability
mass.

The construction is parameterized by an `offset` value (default 0.9677083) that
determines the outermost quantile boundary — the CDF value beyond which tail
probability is excluded. The resulting codebook is normalized so that the largest
absolute value maps to 1.0.

The NF4 type must include an exact zero representation to enable lossless
quantization of padding and sparse zero elements.

## FP4 (4-bit Floating Point) Data Type

FP4 is an IEEE 754-inspired 4-bit floating point format. The 4-bit encoding uses
1 sign bit, 2 exponent bits, and 1 mantissa bit. The exponent bias follows the
standard convention for the given exponent width. Like IEEE 754, exponent-zero
entries are treated as subnormals (no implicit leading 1 in the significand).
Signed encoding produces both positive and negative variants of each magnitude.
The final codebook is sorted and normalized to [-1, 1].

## 4-bit Packing

Two 4-bit codebook indices are stored in a single uint8 byte. The first element
occupies the lower nibble (bits 0-3) and the second element occupies the upper
nibble (bits 4-7). Input tensors with an odd number of elements are padded to
even length before packing.

## Double Quantization

Storing a float32 absolute-maximum value per block creates non-trivial memory
overhead (32 bits per block of typically 64 weights). Double quantization
reduces this overhead by applying a secondary quantization pass to the
per-block scaling factors themselves, compressing them from float32 to a more
compact representation.

The secondary quantization uses its own block structure (typically grouping 256
first-level blocks together) and produces its own quantization state. The offset
(mean of the original scaling factors) is subtracted before secondary quantization
to center the values around zero, improving quantization accuracy.

## Dynamic Quantization Maps

The 8-bit quantization used in the secondary pass employs a non-uniform
quantization map with 256 levels. Unlike the fixed-grid NF4 approach, this map
uses a variable-exponent structure where the density of quantization levels is
concentrated near zero, providing finer granularity where values are most likely
to cluster. Higher exponent bands cover larger magnitudes with correspondingly
coarser resolution. The map is symmetric (signed) and must include both zero and
1.0 among its representable values.
