package gorillachunk

// MergeChunks merges two XORChunks into a single new chunk.
//
// All samples from both chunks are included in the result, ordered by
// timestamp. When both chunks contain a sample at the same timestamp,
// the value from chunk 'a' is kept and the value from chunk 'b' is
// discarded (deduplication).
//
// Returns an error if either chunk's iterator encounters an error.
func MergeChunks(a, b *XORChunk) (*XORChunk, error) {
	panic("not implemented")
}
