package main


import "encoding/binary"

// Free list constants
const FREE_LIST_HEADER = 8
const FREE_LIST_CAP = (BTREE_PAGE_SIZE - FREE_LIST_HEADER) / 8

// LNode is a free list node stored in a database page.
// Node format:
//
//	| next_ptr (8B) | page_numbers (n * 8B) |
type LNode []byte

// FreeList manages free pages using an unrolled linked list.
type FreeList struct {
	get func(uint64) []byte
	new func([]byte) uint64
	set func(uint64) []byte

	headPage uint64
	headSeq  uint64
	tailPage uint64
	tailSeq  uint64

	maxSeq uint64
}

func seq2idx(seq uint64) int {
	return int(seq % uint64(FREE_LIST_CAP))
}

// --- LNode getters/setters ---

func (node LNode) getNext() uint64 {
	return binary.LittleEndian.Uint64(node[:8])
}

func (node LNode) setNext(next uint64) {
	binary.LittleEndian.PutUint64(node[:8], next)
}

func (node LNode) getPtr(idx int) uint64 {
	offset := FREE_LIST_HEADER + 8*idx
	return binary.LittleEndian.Uint64(node[offset:])
}

func (node LNode) setPtr(idx int, ptr uint64) {
	offset := FREE_LIST_HEADER + 8*idx
	binary.LittleEndian.PutUint64(node[offset:], ptr)
}

// flPop removes 1 item from the head node and returns it.
// Also returns the page number of the emptied head node (if it became empty), else 0.
func flPop(fl *FreeList) (ptr uint64, head uint64) {
	if fl.headSeq == fl.maxSeq {
		return 0, 0 // cannot advance
	}
	node := LNode(fl.get(fl.headPage))
	ptr = node.getPtr(seq2idx(fl.headSeq))
	fl.headSeq++
	// move to the next node if the head node is fully consumed
	if seq2idx(fl.headSeq) == 0 {
		head, fl.headPage = fl.headPage, node.getNext()
		assert(fl.headPage != 0)
	}
	return
}

// PopHead removes and returns 1 item from the free list head.
// Returns 0 if the list is empty or headSeq has reached maxSeq.
func (fl *FreeList) PopHead() uint64 {
	ptr, head := flPop(fl)
	if head != 0 {
		// recycle the emptied head node
		fl.PushTail(head)
	}
	return ptr
}

// PushTail adds 1 item to the tail of the free list.
func (fl *FreeList) PushTail(ptr uint64) {
	// append the item to the tail node
	LNode(fl.set(fl.tailPage)).setPtr(seq2idx(fl.tailSeq), ptr)
	fl.tailSeq++
	// if the tail node is full, allocate a new tail node
	if seq2idx(fl.tailSeq) == 0 {
		// try to reuse a page from the list head
		next, head := flPop(fl)
		if next == 0 {
			// no reusable page; append a new one
			next = fl.new(make([]byte, BTREE_PAGE_SIZE))
		}
		// link the old tail to the new tail
		LNode(fl.set(fl.tailPage)).setNext(next)
		fl.tailPage = next
		// if flPop removed the head node, recycle it into the new tail
		if head != 0 {
			LNode(fl.set(fl.tailPage)).setPtr(0, head)
			fl.tailSeq++
		}
	}
}

// SetMaxSeq makes newly added items available for consumption.
func (fl *FreeList) SetMaxSeq() {
	fl.maxSeq = fl.tailSeq
}
