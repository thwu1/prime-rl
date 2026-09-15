package main

import (
	"encoding/binary"
	"fmt"
	"os"
)


// DB_SIG identifies the database file format.
// Update this if you change the meta page layout.
const DB_SIG = "BuildYourOwnDB06"

// KV is an append-only key-value store backed by a copy-on-write B+tree.
//
// Current limitations:
//   - Pages are never recycled. Every update appends new pages to the file.
//   - After many insert/delete cycles, the file grows without bound.
//
// The file layout is:
//
//	| meta_page (page 0) | data pages ... |
//
// Meta page format:
//
//	| sig (16B) | root_ptr (8B) | page_used (8B) |
type KV struct {
	Path string
	fp   *os.File
	tree BTree
	page struct {
		flushed uint64   // database size in number of pages
		temp    [][]byte // newly allocated pages awaiting flush
	}
}

// Open opens or creates the database file.
func (db *KV) Open() error {
	fp, err := os.OpenFile(db.Path, os.O_RDWR|os.O_CREATE, 0644)
	if err != nil {
		return fmt.Errorf("open file: %w", err)
	}
	db.fp = fp

	// B+tree callbacks
	db.tree.get = db.pageRead    // read a page
	db.tree.new = db.pageAppend  // allocate by appending
	db.tree.del = func(uint64) {} // no-op: pages are never recycled

	// Read the meta page
	info, err := db.fp.Stat()
	if err != nil {
		return fmt.Errorf("stat file: %w", err)
	}
	return db.readRoot(info.Size())
}

// Close closes the database file.
func (db *KV) Close() {
	if db.fp != nil {
		_ = db.fp.Sync()
		_ = db.fp.Close()
		db.fp = nil
	}
}

// Get returns the value for a key, or (nil, false) if not found.
func (db *KV) Get(key []byte) ([]byte, bool) {
	return db.tree.Get(key)
}

// Set inserts or updates a key.
func (db *KV) Set(key []byte, val []byte) error {
	if err := db.tree.Insert(key, val); err != nil {
		return err
	}
	return db.updateFile()
}

// Del deletes a key. Returns true if the key existed.
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

// pageRead reads a page from the database file.
func (db *KV) pageRead(ptr uint64) []byte {
	data := make([]byte, BTREE_PAGE_SIZE)
	_, err := db.fp.ReadAt(data, int64(ptr)*int64(BTREE_PAGE_SIZE))
	if err != nil {
		panic(fmt.Sprintf("pageRead(%d): %v", ptr, err))
	}
	return data
}

// pageAppend allocates a new page by appending to the file.
// The page is buffered in memory until writePages is called.
func (db *KV) pageAppend(node []byte) uint64 {
	assert(len(node) == BTREE_PAGE_SIZE)
	ptr := db.page.flushed + uint64(len(db.page.temp))
	db.page.temp = append(db.page.temp, node)
	return ptr
}

// --- Persistence (two-phase update protocol) ---

// writePages flushes all buffered pages to the file.
func (db *KV) writePages() error {
	for i, page := range db.page.temp {
		offset := int64(db.page.flushed+uint64(i)) * int64(BTREE_PAGE_SIZE)
		if _, err := db.fp.WriteAt(page, offset); err != nil {
			return fmt.Errorf("write page: %w", err)
		}
	}
	db.page.flushed += uint64(len(db.page.temp))
	db.page.temp = db.page.temp[:0]
	return nil
}

// saveMeta serializes the meta page.
func (db *KV) saveMeta() []byte {
	var data [32]byte
	copy(data[:16], []byte(DB_SIG))
	binary.LittleEndian.PutUint64(data[16:], db.tree.root)
	binary.LittleEndian.PutUint64(data[24:], db.page.flushed)
	return data[:]
}

// loadMeta deserializes the meta page into in-memory state.
func (db *KV) loadMeta(data []byte) {
	db.tree.root = binary.LittleEndian.Uint64(data[16:])
	db.page.flushed = binary.LittleEndian.Uint64(data[24:])
}

// updateRoot writes the meta page to the beginning of the file.
func (db *KV) updateRoot() error {
	if _, err := db.fp.WriteAt(db.saveMeta(), 0); err != nil {
		return fmt.Errorf("write meta page: %w", err)
	}
	return nil
}

// updateFile performs the two-phase update:
//  1. Write new data pages, then fsync.
//  2. Update the meta page, then fsync.
//
// This ensures crash safety: if a crash occurs between steps 1 and 2,
// the old meta page still points to valid data.
func (db *KV) updateFile() error {
	// Phase 1: write new pages
	if err := db.writePages(); err != nil {
		return err
	}
	if err := db.fp.Sync(); err != nil {
		return err
	}
	// Phase 2: update the meta page
	if err := db.updateRoot(); err != nil {
		return err
	}
	return db.fp.Sync()
}

// readRoot loads the meta page on startup.
func (db *KV) readRoot(fileSize int64) error {
	if fileSize == 0 {
		// Empty file: reserve page 0 for the meta page.
		db.page.flushed = 1
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
	return nil
}
