package main

import "encoding/binary"


const FREE_LIST_HEADER = 8
const FREE_LIST_CAP = (BTREE_PAGE_SIZE - FREE_LIST_HEADER) / 8

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

type LNode []byte

func (n LNode) getNext() uint64            { return binary.LittleEndian.Uint64(n[0:8]) }
func (n LNode) setNext(next uint64)        { binary.LittleEndian.PutUint64(n[0:8], next) }
func (n LNode) getPtr(idx int) uint64      { return binary.LittleEndian.Uint64(n[FREE_LIST_HEADER+8*idx:]) }
func (n LNode) setPtr(idx int, ptr uint64) { binary.LittleEndian.PutUint64(n[FREE_LIST_HEADER+8*idx:], ptr) }

func seq2idx(seq uint64) int {
	return int(seq % FREE_LIST_CAP)
}

func (fl *FreeList) Total() int {
	return int(fl.tailSeq - fl.headSeq)
}

// flPop removes one item from the head without recycling the empty head node.
// Returns the item (ptr) and the old head page number if the head node is now empty.
func flPop(fl *FreeList) (ptr uint64, head uint64) {
	if fl.headSeq == fl.maxSeq {
		return 0, 0 // cannot advance past maxSeq
	}
	node := LNode(fl.get(fl.headPage))
	ptr = node.getPtr(seq2idx(fl.headSeq))
	fl.headSeq++
	// move to the next node if the head is now empty
	if seq2idx(fl.headSeq) == 0 {
		head, fl.headPage = fl.headPage, node.getNext()
		assert(fl.headPage != 0)
	}
	return
}

func (fl *FreeList) PopHead() uint64 {
	ptr, head := flPop(fl)
	if head != 0 {
		// the empty head node is itself a freed page — recycle it
		fl.PushTail(head)
	}
	return ptr
}

func (fl *FreeList) PushTail(ptr uint64) {
	// append the item to the tail node
	LNode(fl.set(fl.tailPage)).setPtr(seq2idx(fl.tailSeq), ptr)
	fl.tailSeq++
	// if the tail node is now full, allocate a new tail
	if seq2idx(fl.tailSeq) == 0 {
		// try to reuse a page from the head
		next, head := flPop(fl)
		if next == 0 {
			// no reusable page; append a new one
			next = fl.new(make([]byte, BTREE_PAGE_SIZE))
		}
		// link old tail to new tail
		LNode(fl.set(fl.tailPage)).setNext(next)
		fl.tailPage = next
		// if flPop removed a head node, recycle it into the new tail
		if head != 0 {
			LNode(fl.set(fl.tailPage)).setPtr(0, head)
			fl.tailSeq++
		}
	}
}

func (fl *FreeList) SetMaxSeq() {
	fl.maxSeq = fl.tailSeq
}
