package main


// Free list constants
const FREE_LIST_HEADER = 8
const FREE_LIST_CAP = (BTREE_PAGE_SIZE - FREE_LIST_HEADER) / 8

// LNode is a free list node stored in a database page.
// Node format:
//
//	| next_ptr (8B) | page_numbers (n * 8B) |
//
// Each node can store up to FREE_LIST_CAP page numbers.
type LNode []byte

// FreeList manages free (deleted) pages using an unrolled linked list
// stored in database pages. Items are pushed to the tail and popped
// from the head. Sequence numbers track positions within the list.
//
// The free list is self-managing: when it needs a new list node, it
// first tries to reuse a page from itself before appending a new one.
//
// maxSeq prevents consuming items that were added during the current
// update, ensuring crash safety with the two-phase update protocol.
type FreeList struct {
	// callbacks for managing on-disk pages
	get func(uint64) []byte  // read a page
	new func([]byte) uint64  // append a new page
	set func(uint64) []byte  // get a writable copy of an existing page

	// persisted state (saved in the meta page)
	headPage uint64
	headSeq  uint64
	tailPage uint64
	tailSeq  uint64

	// in-memory state
	maxSeq uint64 // saved tailSeq; headSeq cannot advance past this
}

// seq2idx converts a monotonic sequence number to an index within a node.
func seq2idx(seq uint64) int {
	return int(seq % uint64(FREE_LIST_CAP))
}

// --- LNode getters/setters ---

func (node LNode) getNext() uint64 {
	// TODO: implement
	panic("not implemented")
}

func (node LNode) setNext(next uint64) {
	// TODO: implement
	panic("not implemented")
}

func (node LNode) getPtr(idx int) uint64 {
	// TODO: implement
	panic("not implemented")
}

func (node LNode) setPtr(idx int, ptr uint64) {
	// TODO: implement
	panic("not implemented")
}

// PopHead removes and returns 1 item from the head of the free list.
// Returns 0 if the list is empty or if headSeq has reached maxSeq.
// When the head node becomes empty, it is recycled by pushing it to the tail.
func (fl *FreeList) PopHead() uint64 {
	// TODO: implement
	panic("not implemented")
}

// PushTail adds 1 item (a freed page number) to the tail of the free list.
// When the tail node is full, a new tail node is obtained — first by
// trying PopHead (self-management), then by calling fl.new (append).
func (fl *FreeList) PushTail(ptr uint64) {
	// TODO: implement
	panic("not implemented")
}

// SetMaxSeq advances maxSeq to tailSeq, making newly added items
// available for consumption in subsequent updates.
func (fl *FreeList) SetMaxSeq() {
	// TODO: implement
	panic("not implemented")
}
