package main

import (
	"encoding/binary"
	"fmt"
	"os"
)


const DB_SIG = "FreeListKV000001"

// ioTraceWriter enables I/O tracing when non-nil.
// Set this to an open file before running KV operations to capture
// a trace of all WriteAt and Sync calls on the database file.
var ioTraceWriter *os.File

func ioTrace(format string, args ...interface{}) {
	if ioTraceWriter != nil {
		fmt.Fprintf(ioTraceWriter, format+"\n", args...)
	}
}

// KV is a key-value store backed by a copy-on-write B+tree with page recycling.
type KV struct {
	Path string
	fp   *os.File
	tree BTree
	free FreeList
	page struct {
		flushed uint64               // database size in number of pages
		nappend uint64               // number of pages to be appended
		updates map[uint64][]byte    // pending updates (appended + in-place)
	}
}

func (db *KV) Open() error {
	fp, err := os.OpenFile(db.Path, os.O_RDWR|os.O_CREATE, 0644)
	if err != nil {
		return fmt.Errorf("open file: %w", err)
	}
	db.fp = fp
	db.page.updates = make(map[uint64][]byte)

	// B+tree callbacks
	db.tree.get = db.pageRead
	db.tree.new = db.pageAlloc
	db.tree.del = db.free.PushTail

	// Free list callbacks
	db.free.get = db.pageRead
	db.free.new = db.pageAppend
	db.free.set = db.pageWrite

	info, err := db.fp.Stat()
	if err != nil {
		return fmt.Errorf("stat file: %w", err)
	}
	return db.readRoot(info.Size())
}

func (db *KV) Close() {
	if db.fp != nil {
		ioTrace("FSYNC (close)")
		_ = db.fp.Sync()
		_ = db.fp.Close()
		db.fp = nil
	}
}

func (db *KV) Get(key []byte) ([]byte, bool) {
	return db.tree.Get(key)
}

func (db *KV) Set(key []byte, val []byte) error {
	if err := db.tree.Insert(key, val); err != nil {
		return err
	}
	return db.updateFile()
}

func (db *KV) Del(key []byte) (bool, error) {
	deleted, err := db.tree.Delete(key)
	if err != nil {
		return false, err
	}
	if !deleted {
		return false, nil
	}
	return true, db.updateFile()
}

// --- Page management ---

// pageRead reads a page, checking pending updates first.
func (db *KV) pageRead(ptr uint64) []byte {
	if node, ok := db.page.updates[ptr]; ok {
		return node
	}
	return db.pageReadFile(ptr)
}

// pageReadFile reads a page directly from the file.
func (db *KV) pageReadFile(ptr uint64) []byte {
	data := make([]byte, BTREE_PAGE_SIZE)
	_, err := db.fp.ReadAt(data, int64(ptr)*int64(BTREE_PAGE_SIZE))
	if err != nil {
		panic(fmt.Sprintf("pageReadFile(%d): %v", ptr, err))
	}
	return data
}

// pageAppend allocates a new page by appending (used by the free list).
func (db *KV) pageAppend(node []byte) uint64 {
	assert(len(node) == BTREE_PAGE_SIZE)
	ptr := db.page.flushed + db.page.nappend
	db.page.nappend++
	db.page.updates[ptr] = node
	return ptr
}

// pageAlloc allocates a page, trying the free list first.
func (db *KV) pageAlloc(node []byte) uint64 {
	if ptr := db.free.PopHead(); ptr != 0 {
		db.page.updates[ptr] = node
		return ptr
	}
	return db.pageAppend(node)
}

// pageWrite returns a writable copy of an existing page (for in-place updates).
func (db *KV) pageWrite(ptr uint64) []byte {
	if node, ok := db.page.updates[ptr]; ok {
		return node
	}
	node := make([]byte, BTREE_PAGE_SIZE)
	copy(node, db.pageReadFile(ptr))
	db.page.updates[ptr] = node
	return node
}

// --- Persistence ---

func (db *KV) writePages() error {
	for ptr, page := range db.page.updates {
		offset := int64(ptr) * int64(BTREE_PAGE_SIZE)
		ioTrace("WRITEAT page=%d offset=%d size=%d type=data", ptr, offset, len(page))
		if _, err := db.fp.WriteAt(page, offset); err != nil {
			return fmt.Errorf("write page %d: %w", ptr, err)
		}
	}
	db.page.flushed += db.page.nappend
	db.page.nappend = 0
	db.page.updates = make(map[uint64][]byte)
	return nil
}

func (db *KV) saveMeta() []byte {
	var data [64]byte
	copy(data[:16], []byte(DB_SIG))
	binary.LittleEndian.PutUint64(data[16:], db.tree.root)
	binary.LittleEndian.PutUint64(data[24:], db.page.flushed)
	binary.LittleEndian.PutUint64(data[32:], db.free.headPage)
	binary.LittleEndian.PutUint64(data[40:], db.free.headSeq)
	binary.LittleEndian.PutUint64(data[48:], db.free.tailPage)
	binary.LittleEndian.PutUint64(data[56:], db.free.tailSeq)
	return data[:]
}

func (db *KV) loadMeta(data []byte) {
	db.tree.root = binary.LittleEndian.Uint64(data[16:])
	db.page.flushed = binary.LittleEndian.Uint64(data[24:])
	db.free.headPage = binary.LittleEndian.Uint64(data[32:])
	db.free.headSeq = binary.LittleEndian.Uint64(data[40:])
	db.free.tailPage = binary.LittleEndian.Uint64(data[48:])
	db.free.tailSeq = binary.LittleEndian.Uint64(data[56:])
}

func (db *KV) updateRoot() error {
	meta := db.saveMeta()
	ioTrace("WRITEAT page=0 offset=0 size=%d type=meta", len(meta))
	if _, err := db.fp.WriteAt(meta, 0); err != nil {
		return fmt.Errorf("write meta page: %w", err)
	}
	return nil
}

func (db *KV) updateFile() error {
	// Phase 1: write data pages
	if err := db.writePages(); err != nil {
		return err
	}
	ioTrace("FSYNC phase=1 (data pages flushed to disk)")
	if err := db.fp.Sync(); err != nil {
		return err
	}
	// Phase 2: update meta page
	if err := db.updateRoot(); err != nil {
		return err
	}
	ioTrace("FSYNC phase=2 (meta page flushed to disk)")
	if err := db.fp.Sync(); err != nil {
		return err
	}
	// Prepare free list for the next update
	db.free.SetMaxSeq()
	return nil
}

func (db *KV) readRoot(fileSize int64) error {
	if fileSize == 0 {
		// Empty file: reserve page 0 (meta) and page 1 (initial free list node)
		db.page.flushed = 2
		db.free.headPage = 1
		db.free.tailPage = 1
		return nil
	}
	data := make([]byte, BTREE_PAGE_SIZE)
	if _, err := db.fp.ReadAt(data, 0); err != nil {
		return fmt.Errorf("read meta page: %w", err)
	}
	if string(data[:16]) != DB_SIG {
		return fmt.Errorf("bad database signature")
	}
	db.loadMeta(data)
	// Restore maxSeq from persisted tailSeq
	db.free.maxSeq = db.free.tailSeq
	return nil
}
