package main

import "encoding/binary"

// FreeList manages reusable disk pages using an on-disk unrolled linked list.
//
// Each list node occupies one page with this format:
//   | next (8B) | pointers (n × 8B) | unused |
//
// Items (freed page numbers) are consumed from the head and appended to the
// tail. The list always contains at least one node.
//
// The free list is self-managing:
// - When it needs a new node for the tail, it tries to reuse a page from
//   its own head before allocating a new page via the `new` callback.
// - When the head node becomes empty, it is recycled by pushing it to the tail.
//
// The maxSeq field prevents consuming items added during the current update.
// This is critical: pages freed during an update are still referenced by the
// current B+tree version until the meta page is committed. Consuming them
// would cause use-after-free corruption.

const FREE_LIST_HEADER = 8
const FREE_LIST_CAP = (BTREE_PAGE_SIZE - FREE_LIST_HEADER) / 8

// FreeList tracks freed pages for reuse
type FreeList struct {
	// Callbacks for managing on-disk pages
	get func(uint64) []byte // read a page
	new func([]byte) uint64 // append a new page
	set func(uint64) []byte // get a writable copy of an existing page

	// Persisted state (must be saved in the meta page)
	headPage uint64 // pointer to the list head node
	headSeq  uint64 // monotonic sequence number indexing into the head
	tailPage uint64 // pointer to the list tail node
	tailSeq  uint64 // monotonic sequence number indexing into the tail

	// In-memory state
	maxSeq uint64 // saved tailSeq — headSeq cannot advance past this
}

// LNode is a free list node stored in a single page
type LNode []byte

func (n LNode) getNext() uint64            { return binary.LittleEndian.Uint64(n[0:8]) }
func (n LNode) setNext(next uint64)        { binary.LittleEndian.PutUint64(n[0:8], next) }
func (n LNode) getPtr(idx int) uint64      { return binary.LittleEndian.Uint64(n[FREE_LIST_HEADER+8*idx:]) }
func (n LNode) setPtr(idx int, ptr uint64) { binary.LittleEndian.PutUint64(n[FREE_LIST_HEADER+8*idx:], ptr) }

// seq2idx converts a monotonic sequence number to an index within a node
func seq2idx(seq uint64) int {
	return int(seq % FREE_LIST_CAP)
}

// Total returns the number of items currently in the free list
func (fl *FreeList) Total() int {
	return int(fl.tailSeq - fl.headSeq)
}

// PopHead removes and returns one item from the head of the free list.
// Returns 0 if the list is empty or if headSeq has reached maxSeq
// (preventing consumption of items added during the current update).
//
// When the head node becomes completely empty after removal, it must be
// recycled by pushing it to the tail via PushTail.
func (fl *FreeList) PopHead() uint64 {
	// TODO: implement
	return 0
}

// PushTail appends one item (a freed page number) to the tail of the list.
//
// When the tail node becomes full after appending:
// 1. Allocate a new page for the next tail node. Try to reuse a page from
//    the list head (via an internal pop) before resorting to fl.new().
// 2. Link the old tail to the new tail via the next pointer.
// 3. If the internal pop emptied and removed a head node, that head node
//    must also be pushed to the new tail (it too is a freed page).
func (fl *FreeList) PushTail(ptr uint64) {
	// TODO: implement
}

// SetMaxSeq advances maxSeq to the current tailSeq.
// Call this between updates to allow items from the previous update
// to be consumed in the next update.
func (fl *FreeList) SetMaxSeq() {
	// TODO: implement
}
