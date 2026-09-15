package main

import (
	"encoding/binary"
	"fmt"
	"os"
)

const DB_SIG = "BuildYourOwnDB07"

type KV struct {
	Path string
	fp   *os.File
	tree BTree
	page struct {
		flushed uint64
		nappend int
		updates map[uint64][]byte
	}
}

func (db *KV) Open() error {
	fp, err := os.OpenFile(db.Path, os.O_RDWR|os.O_CREATE, 0644)
	if err != nil {
		return err
	}
	db.fp = fp
	db.page.updates = make(map[uint64][]byte)

	db.tree.get = db.pageRead
	db.tree.new = db.pageAppend
	db.tree.del = func(uint64) {}

	fi, err := db.fp.Stat()
	if err != nil {
		return err
	}
	return db.readRoot(fi.Size())
}

func (db *KV) Close() {
	db.fp.Close()
}

func (db *KV) pageReadFile(ptr uint64) []byte {
	data := make([]byte, BTREE_PAGE_SIZE)
	_, err := db.fp.ReadAt(data, int64(ptr)*int64(BTREE_PAGE_SIZE))
	if err != nil {
		panic(fmt.Sprintf("pageReadFile(%d): %v", ptr, err))
	}
	return data
}

func (db *KV) pageRead(ptr uint64) []byte {
	if node, ok := db.page.updates[ptr]; ok {
		return node
	}
	return db.pageReadFile(ptr)
}

func (db *KV) pageAppend(node []byte) uint64 {
	assert(len(node) == BTREE_PAGE_SIZE)
	ptr := db.page.flushed + uint64(db.page.nappend)
	db.page.nappend++
	db.page.updates[ptr] = node
	return ptr
}

// Meta page format:
//
//	| sig (16B) | root_ptr (8B) | page_used (8B) |
func (db *KV) saveMeta() []byte {
	var data [64]byte
	copy(data[:16], []byte(DB_SIG))
	binary.LittleEndian.PutUint64(data[16:], db.tree.root)
	binary.LittleEndian.PutUint64(data[24:], db.page.flushed+uint64(db.page.nappend))
	return data[:]
}

func (db *KV) loadMeta(data []byte) {
	db.tree.root = binary.LittleEndian.Uint64(data[16:])
	db.page.flushed = binary.LittleEndian.Uint64(data[24:])
}

func (db *KV) readRoot(fileSize int64) error {
	if fileSize == 0 {
		db.page.flushed = 1
		return nil
	}
	if fileSize < BTREE_PAGE_SIZE {
		return fmt.Errorf("file too small: %d", fileSize)
	}
	data := db.pageReadFile(0)
	if string(data[:16]) != DB_SIG {
		return fmt.Errorf("bad signature: %q", string(data[:16]))
	}
	db.loadMeta(data)
	return nil
}

func (db *KV) writePages() error {
	for ptr, data := range db.page.updates {
		if _, err := db.fp.WriteAt(data, int64(ptr)*int64(BTREE_PAGE_SIZE)); err != nil {
			return err
		}
	}
	return nil
}

func (db *KV) updateRoot() error {
	data := db.saveMeta()
	if _, err := db.fp.WriteAt(data, 0); err != nil {
		return fmt.Errorf("write meta: %w", err)
	}
	return nil
}

func (db *KV) updateFile() error {
	if err := db.writePages(); err != nil {
		return err
	}
	if err := db.fp.Sync(); err != nil {
		return err
	}
	if err := db.updateRoot(); err != nil {
		return err
	}
	if err := db.fp.Sync(); err != nil {
		return err
	}
	db.page.flushed += uint64(db.page.nappend)
	db.page.nappend = 0
	db.page.updates = make(map[uint64][]byte)
	return nil
}

func (db *KV) Get(key []byte) ([]byte, bool) {
	return db.tree.Get(key)
}

func (db *KV) Set(key, val []byte) error {
	if err := db.tree.Insert(key, val); err != nil {
		return err
	}
	return db.updateFile()
}

func (db *KV) Del(key []byte) (bool, error) {
	deleted := db.tree.Delete(key)
	return deleted, db.updateFile()
}

func (db *KV) Scan(cb func(key, val []byte)) {
	db.tree.Scan(cb)
}

func (db *KV) PageCount() uint64 {
	return db.page.flushed + uint64(db.page.nappend)
}
