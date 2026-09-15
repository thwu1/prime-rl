package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"hash/crc32"
	"os"
	"path/filepath"
	"sort"
)

var (
	segmentMagic  = [4]byte{0x52, 0x4C, 0x4F, 0x47}
	snapshotMagic = [4]byte{0x52, 0x53, 0x4E, 0x50}
)

const currentVersion uint16 = 1

type Entry struct {
	Index     uint64
	Term      uint64
	Timestamp int64
	Payload   []byte
}

type SnapshotData struct {
	LastIndex uint64
	LastTerm  uint64
	State     map[string]string
}

type WALWriter struct {
	dir           string
	entriesPerSeg int
	allEntries    []Entry
}

func NewWALWriter(dir string, entriesPerSeg int) *WALWriter {
	return &WALWriter{dir: dir, entriesPerSeg: entriesPerSeg}
}

func (w *WALWriter) Append(entry Entry) {
	w.allEntries = append(w.allEntries, entry)
}

func (w *WALWriter) Flush() error {
	for i := 0; i < len(w.allEntries); i += w.entriesPerSeg {
		end := i + w.entriesPerSeg
		if end > len(w.allEntries) {
			end = len(w.allEntries)
		}
		if err := w.writeSegment(w.allEntries[i:end]); err != nil {
			return err
		}
	}
	return nil
}

func (w *WALWriter) writeSegment(entries []Entry) error {
	if len(entries) == 0 {
		return nil
	}
	firstIdx := entries[0].Index
	path := filepath.Join(w.dir, segmentFilename(firstIdx))
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	f.Write(segmentMagic[:])
	binary.Write(f, binary.LittleEndian, currentVersion)
	binary.Write(f, binary.LittleEndian, firstIdx)
	binary.Write(f, binary.LittleEndian, uint32(len(entries)))

	for _, e := range entries {
		f.Write(marshalEntry(e))
	}
	return nil
}

func marshalEntry(e Entry) []byte {
	size := 8 + 8 + 8 + 4 + len(e.Payload)
	buf := make([]byte, size)

	binary.LittleEndian.PutUint64(buf[0:8], e.Index)
	binary.LittleEndian.PutUint64(buf[8:16], e.Term)
	binary.LittleEndian.PutUint64(buf[16:24], uint64(e.Timestamp))
	binary.LittleEndian.PutUint32(buf[24:28], uint32(len(e.Payload)))
	copy(buf[28:], e.Payload)

	checksum := crc32.ChecksumIEEE(buf)
	crcBytes := make([]byte, 4)
	binary.LittleEndian.PutUint32(crcBytes, checksum)

	return append(buf, crcBytes...)
}

func (w *WALWriter) WriteSnapshot(lastIdx, lastTerm uint64, state map[string]string) error {
	path := filepath.Join(w.dir, snapshotFilename(lastIdx))
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	stateJSON, _ := json.Marshal(state)

	headerSize := 4 + 2 + 8 + 8 + 4 + len(stateJSON)
	buf := make([]byte, headerSize)

	copy(buf[0:4], snapshotMagic[:])
	binary.LittleEndian.PutUint16(buf[4:6], currentVersion)
	binary.LittleEndian.PutUint64(buf[6:14], lastIdx)
	binary.LittleEndian.PutUint64(buf[14:22], lastTerm)
	binary.LittleEndian.PutUint32(buf[22:26], uint32(len(stateJSON)))
	copy(buf[26:], stateJSON)

	checksum := crc32.ChecksumIEEE(buf)
	crcBytes := make([]byte, 4)
	binary.LittleEndian.PutUint32(crcBytes, checksum)

	f.Write(buf)
	f.Write(crcBytes)
	return nil
}

func (w *WALWriter) CompactBefore(snapIdx uint64) {
	matches, _ := filepath.Glob(filepath.Join(w.dir, "segment_*.wal"))
	sort.Strings(matches)

	for _, path := range matches {
		data, err := os.ReadFile(path)
		if err != nil || len(data) < 18 {
			continue
		}
		firstIdx := binary.LittleEndian.Uint64(data[6:14])
		entryCount := binary.LittleEndian.Uint32(data[14:18])
		lastIdx := firstIdx + uint64(entryCount) - 1
		if lastIdx <= snapIdx {
			os.Remove(path)
		}
	}
}

func readSegmentEntries(path string) ([]Entry, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 18 {
		return nil, fmt.Errorf("segment too short")
	}
	if string(data[0:4]) != string(segmentMagic[:]) {
		return nil, fmt.Errorf("bad segment magic")
	}

	entryCount := binary.LittleEndian.Uint32(data[14:18])

	var entries []Entry
	offset := 18
	for i := uint32(0); i < entryCount; i++ {
		if offset+28 > len(data) {
			return entries, fmt.Errorf("truncated at entry %d", i)
		}

		idx := binary.LittleEndian.Uint64(data[offset : offset+8])
		term := binary.LittleEndian.Uint64(data[offset+8 : offset+16])
		ts := int64(binary.LittleEndian.Uint64(data[offset+16 : offset+24]))
		payloadLen := binary.LittleEndian.Uint32(data[offset+24 : offset+28])

		entryEnd := offset + 28 + int(payloadLen) + 4
		if entryEnd > len(data) {
			return entries, fmt.Errorf("truncated entry index=%d at offset %d", idx, offset)
		}

		payload := make([]byte, payloadLen)
		copy(payload, data[offset+28:offset+28+int(payloadLen)])

		storedCRC := binary.LittleEndian.Uint32(data[offset+28+int(payloadLen) : entryEnd])
		computedCRC := crc32.ChecksumIEEE(data[offset : offset+28+int(payloadLen)])
		if storedCRC != computedCRC {
			return entries, fmt.Errorf("CRC mismatch at entry index=%d: stored=%08x computed=%08x",
				idx, storedCRC, computedCRC)
		}

		entries = append(entries, Entry{
			Index:     idx,
			Term:      term,
			Timestamp: ts,
			Payload:   payload,
		})
		offset = entryEnd
	}

	return entries, nil
}

func ReadSnapshot(dir string) (*SnapshotData, error) {
	matches, _ := filepath.Glob(filepath.Join(dir, "snapshot_*.snap"))
	if len(matches) == 0 {
		return nil, nil
	}
	sort.Strings(matches)
	path := matches[len(matches)-1]

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) < 30 {
		return nil, fmt.Errorf("snapshot too short")
	}
	if string(data[0:4]) != string(snapshotMagic[:]) {
		return nil, fmt.Errorf("bad snapshot magic")
	}

	storedCRC := binary.LittleEndian.Uint32(data[len(data)-4:])
	computedCRC := crc32.ChecksumIEEE(data[:len(data)-4])
	if storedCRC != computedCRC {
		return nil, fmt.Errorf("snapshot CRC mismatch: stored=%08x computed=%08x",
			storedCRC, computedCRC)
	}

	lastIdx := binary.LittleEndian.Uint64(data[6:14])
	lastTerm := binary.LittleEndian.Uint64(data[14:22])
	stateLen := binary.LittleEndian.Uint32(data[22:26])

	var state map[string]string
	if err := json.Unmarshal(data[26:26+stateLen], &state); err != nil {
		return nil, err
	}

	return &SnapshotData{
		LastIndex: lastIdx,
		LastTerm:  lastTerm,
		State:     state,
	}, nil
}

func segmentFilename(firstIndex uint64) string {
	return fmt.Sprintf("segment_%010d.wal", firstIndex)
}

func snapshotFilename(lastIndex uint64) string {
	return fmt.Sprintf("snapshot_%010d.snap", lastIndex)
}
