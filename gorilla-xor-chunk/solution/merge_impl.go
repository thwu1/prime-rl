package gorillachunk

import "fmt"

// MergeChunks merges two XORChunks into a single new chunk.
func MergeChunks(a, b *XORChunk) (*XORChunk, error) {
	result := NewXORChunk()
	app, err := result.Appender()
	if err != nil {
		return nil, fmt.Errorf("creating appender: %w", err)
	}

	itA := a.Iterator(nil)
	itB := b.Iterator(nil)

	hasA := itA.Next() == ValFloat
	hasB := itB.Next() == ValFloat

	for hasA || hasB {
		if !hasA {
			tB, vB := itB.At()
			app.Append(tB, vB)
			hasB = itB.Next() == ValFloat
			continue
		}
		if !hasB {
			tA, vA := itA.At()
			app.Append(tA, vA)
			hasA = itA.Next() == ValFloat
			continue
		}

		tA, vA := itA.At()
		tB, vB := itB.At()

		if tA < tB {
			app.Append(tA, vA)
			hasA = itA.Next() == ValFloat
		} else if tB < tA {
			app.Append(tB, vB)
			hasB = itB.Next() == ValFloat
		} else {
			// Same timestamp: keep value from chunk a.
			app.Append(tA, vA)
			hasA = itA.Next() == ValFloat
			hasB = itB.Next() == ValFloat
		}
	}

	if err := itA.Err(); err != nil {
		return nil, fmt.Errorf("iterating chunk a: %w", err)
	}
	if err := itB.Err(); err != nil {
		return nil, fmt.Errorf("iterating chunk b: %w", err)
	}

	return result, nil
}
