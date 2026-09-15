package main

import (
	"bytes"
	"encoding/binary"
	"errors"
)

const (
	BNODE_NODE         = 1 // internal node with child pointers
	BNODE_LEAF         = 2 // leaf node with values
	BTREE_PAGE_SIZE    = 4096
	BTREE_MAX_KEY_SIZE = 1000
	BTREE_MAX_VAL_SIZE = 3000
	HEADER             = 4
)

// BNode is a B+tree node stored as a byte slice (can be dumped to disk).
// Format:
//   | type | nkeys |  pointers  |   offsets    | key-values | unused |
//   |  2B  |   2B  | nkeys × 8B | nkeys × 2B  |     ...    |        |
// KV pair format:
//   | klen | vlen | key | val |
//   |  2B  |  2B  | ... | ... |
type BNode []byte

func (n BNode) btype() uint16 { return binary.LittleEndian.Uint16(n[0:2]) }
func (n BNode) nkeys() uint16 { return binary.LittleEndian.Uint16(n[2:4]) }
func (n BNode) setHeader(btype, nkeys uint16) {
	binary.LittleEndian.PutUint16(n[0:2], btype)
	binary.LittleEndian.PutUint16(n[2:4], nkeys)
}

func (n BNode) getPtr(idx uint16) uint64 {
	assert(idx < n.nkeys())
	return binary.LittleEndian.Uint64(n[4+8*idx:])
}
func (n BNode) setPtr(idx uint16, val uint64) {
	assert(idx < n.nkeys())
	binary.LittleEndian.PutUint64(n[4+8*idx:], val)
}

// The offset of the first KV pair is always 0 and is not stored.
func (n BNode) getOffset(idx uint16) uint16 {
	if idx == 0 {
		return 0
	}
	return binary.LittleEndian.Uint16(n[4+8*n.nkeys()+2*(idx-1):])
}
func (n BNode) setOffset(idx, val uint16) {
	if idx == 0 {
		return
	}
	binary.LittleEndian.PutUint16(n[4+8*n.nkeys()+2*(idx-1):], val)
}

func (n BNode) kvPos(idx uint16) uint16 {
	assert(idx <= n.nkeys())
	return 4 + 8*n.nkeys() + 2*n.nkeys() + n.getOffset(idx)
}

func (n BNode) getKey(idx uint16) []byte {
	assert(idx < n.nkeys())
	pos := n.kvPos(idx)
	klen := binary.LittleEndian.Uint16(n[pos:])
	return n[pos+4:][:klen]
}
func (n BNode) getVal(idx uint16) []byte {
	assert(idx < n.nkeys())
	pos := n.kvPos(idx)
	klen := binary.LittleEndian.Uint16(n[pos:])
	vlen := binary.LittleEndian.Uint16(n[pos+2:])
	return n[pos+4+klen:][:vlen]
}

// nbytes returns the number of bytes used by the node
func (n BNode) nbytes() uint16 {
	return n.kvPos(n.nkeys())
}

// nodeAppendKV copies a KV pair into position idx of the destination node
func nodeAppendKV(dst BNode, idx uint16, ptr uint64, key, val []byte) {
	dst.setPtr(idx, ptr)
	pos := dst.kvPos(idx)
	binary.LittleEndian.PutUint16(dst[pos:], uint16(len(key)))
	binary.LittleEndian.PutUint16(dst[pos+2:], uint16(len(val)))
	copy(dst[pos+4:], key)
	copy(dst[pos+4+uint16(len(key)):], val)
	dst.setOffset(idx+1, dst.getOffset(idx)+4+uint16(len(key)+len(val)))
}

// nodeAppendRange copies n KV pairs from src to dst
func nodeAppendRange(dst, src BNode, dstIdx, srcIdx, n uint16) {
	for i := uint16(0); i < n; i++ {
		nodeAppendKV(dst, dstIdx+i, src.getPtr(srcIdx+i),
			src.getKey(srcIdx+i), src.getVal(srcIdx+i))
	}
}

// nodeLookupLE finds the last position whose key is <= the target key.
// Starts at index 1 to skip the sentinel key at index 0.
func nodeLookupLE(node BNode, key []byte) uint16 {
	found := uint16(0)
	for i := uint16(1); i < node.nkeys(); i++ {
		cmp := bytes.Compare(node.getKey(i), key)
		if cmp <= 0 {
			found = i
		}
		if cmp >= 0 {
			break
		}
	}
	return found
}

func leafInsert(newNode, old BNode, idx uint16, key, val []byte) {
	newNode.setHeader(BNODE_LEAF, old.nkeys()+1)
	nodeAppendRange(newNode, old, 0, 0, idx)
	nodeAppendKV(newNode, idx, 0, key, val)
	nodeAppendRange(newNode, old, idx+1, idx, old.nkeys()-idx)
}

func leafUpdate(newNode, old BNode, idx uint16, key, val []byte) {
	newNode.setHeader(BNODE_LEAF, old.nkeys())
	nodeAppendRange(newNode, old, 0, 0, idx)
	nodeAppendKV(newNode, idx, 0, key, val)
	nodeAppendRange(newNode, old, idx+1, idx+1, old.nkeys()-(idx+1))
}

func leafDelete(newNode, old BNode, idx uint16) {
	newNode.setHeader(BNODE_LEAF, old.nkeys()-1)
	nodeAppendRange(newNode, old, 0, 0, idx)
	nodeAppendRange(newNode, old, idx, idx+1, old.nkeys()-(idx+1))
}

// nodeSplit2 splits an oversized node into 2 so that the right half fits a page
func nodeSplit2(left, right, old BNode) {
	assert(old.nkeys() >= 2)
	nleft := old.nkeys() / 2

	leftBytes := func() uint16 { return 4 + 8*nleft + 2*nleft + old.getOffset(nleft) }
	for leftBytes() > BTREE_PAGE_SIZE {
		nleft--
	}
	assert(nleft >= 1)

	rightBytes := func() uint16 { return old.nbytes() - leftBytes() + HEADER }
	for rightBytes() > BTREE_PAGE_SIZE {
		nleft++
	}
	assert(nleft < old.nkeys())
	nright := old.nkeys() - nleft

	left.setHeader(old.btype(), nleft)
	right.setHeader(old.btype(), nright)
	nodeAppendRange(left, old, 0, 0, nleft)
	nodeAppendRange(right, old, 0, nleft, nright)
	assert(right.nbytes() <= BTREE_PAGE_SIZE)
}

// nodeSplit3 splits a node if too big; result is 1~3 nodes
func nodeSplit3(old BNode) (uint16, [3]BNode) {
	if old.nbytes() <= BTREE_PAGE_SIZE {
		old = old[:BTREE_PAGE_SIZE]
		return 1, [3]BNode{old}
	}
	left := BNode(make([]byte, 2*BTREE_PAGE_SIZE))
	right := BNode(make([]byte, BTREE_PAGE_SIZE))
	nodeSplit2(left, right, old)
	if left.nbytes() <= BTREE_PAGE_SIZE {
		left = left[:BTREE_PAGE_SIZE]
		return 2, [3]BNode{left, right}
	}
	ll := BNode(make([]byte, BTREE_PAGE_SIZE))
	mid := BNode(make([]byte, BTREE_PAGE_SIZE))
	nodeSplit2(ll, mid, left)
	assert(ll.nbytes() <= BTREE_PAGE_SIZE)
	return 3, [3]BNode{ll, mid, right}
}

func nodeMerge(newNode, left, right BNode) {
	newNode.setHeader(left.btype(), left.nkeys()+right.nkeys())
	nodeAppendRange(newNode, left, 0, 0, left.nkeys())
	nodeAppendRange(newNode, right, left.nkeys(), 0, right.nkeys())
}

// nodeReplace2Kid replaces 2 adjacent child links with 1
func nodeReplace2Kid(newNode, old BNode, idx uint16, ptr uint64, key []byte) {
	newNode.setHeader(BNODE_NODE, old.nkeys()-1)
	nodeAppendRange(newNode, old, 0, 0, idx)
	nodeAppendKV(newNode, idx, ptr, key, nil)
	nodeAppendRange(newNode, old, idx+1, idx+2, old.nkeys()-(idx+2))
}

// nodeReplaceKidN replaces 1 child link with multiple links (after split)
func nodeReplaceKidN(tree *BTree, newNode, old BNode, idx uint16, kids ...BNode) {
	inc := uint16(len(kids))
	newNode.setHeader(BNODE_NODE, old.nkeys()+inc-1)
	nodeAppendRange(newNode, old, 0, 0, idx)
	for i, node := range kids {
		nodeAppendKV(newNode, idx+uint16(i), tree.new(node), node.getKey(0), nil)
	}
	nodeAppendRange(newNode, old, idx+inc, idx+1, old.nkeys()-(idx+1))
}

// BTree is the B+tree data structure with page management via callbacks
type BTree struct {
	root uint64
	get  func(uint64) []byte  // dereference a page number
	new  func([]byte) uint64  // allocate a new page
	del  func(uint64)         // deallocate a page
}

func checkLimit(key, val []byte) error {
	if len(key) > BTREE_MAX_KEY_SIZE {
		return errors.New("key too long")
	}
	if len(val) > BTREE_MAX_VAL_SIZE {
		return errors.New("val too long")
	}
	return nil
}

func treeInsert(tree *BTree, node BNode, key, val []byte) BNode {
	newNode := BNode(make([]byte, 2*BTREE_PAGE_SIZE))
	idx := nodeLookupLE(node, key)
	switch node.btype() {
	case BNODE_LEAF:
		if bytes.Equal(key, node.getKey(idx)) {
			leafUpdate(newNode, node, idx, key, val)
		} else {
			leafInsert(newNode, node, idx+1, key, val)
		}
	case BNODE_NODE:
		kptr := node.getPtr(idx)
		knode := treeInsert(tree, tree.get(kptr), key, val)
		nsplit, split := nodeSplit3(knode)
		tree.del(kptr)
		nodeReplaceKidN(tree, newNode, node, idx, split[:nsplit]...)
	}
	return newNode
}

// Insert adds or updates a key in the tree
func (tree *BTree) Insert(key, val []byte) error {
	if err := checkLimit(key, val); err != nil {
		return err
	}
	if tree.root == 0 {
		// create the first root with a sentinel empty key
		root := BNode(make([]byte, BTREE_PAGE_SIZE))
		root.setHeader(BNODE_LEAF, 2)
		nodeAppendKV(root, 0, 0, nil, nil)
		nodeAppendKV(root, 1, 0, key, val)
		tree.root = tree.new(root)
		return nil
	}
	node := treeInsert(tree, tree.get(tree.root), key, val)
	nsplit, split := nodeSplit3(node)
	tree.del(tree.root)
	if nsplit > 1 {
		root := BNode(make([]byte, BTREE_PAGE_SIZE))
		root.setHeader(BNODE_NODE, nsplit)
		for i, knode := range split[:nsplit] {
			nodeAppendKV(root, uint16(i), tree.new(knode), knode.getKey(0), nil)
		}
		tree.root = tree.new(root)
	} else {
		tree.root = tree.new(split[0])
	}
	return nil
}

// Get retrieves a value by key
func (tree *BTree) Get(key []byte) ([]byte, bool) {
	if tree.root == 0 {
		return nil, false
	}
	node := BNode(tree.get(tree.root))
	for {
		idx := nodeLookupLE(node, key)
		switch node.btype() {
		case BNODE_LEAF:
			if bytes.Equal(key, node.getKey(idx)) {
				return node.getVal(idx), true
			}
			return nil, false
		case BNODE_NODE:
			node = BNode(tree.get(node.getPtr(idx)))
		default:
			panic("bad node type")
		}
	}
}

func shouldMerge(tree *BTree, node BNode, idx uint16, updated BNode) (int, BNode) {
	if updated.nbytes() > BTREE_PAGE_SIZE/4 {
		return 0, BNode{}
	}
	if idx > 0 {
		sibling := BNode(tree.get(node.getPtr(idx - 1)))
		if sibling.nbytes()+updated.nbytes()-HEADER <= BTREE_PAGE_SIZE {
			return -1, sibling
		}
	}
	if idx+1 < node.nkeys() {
		sibling := BNode(tree.get(node.getPtr(idx + 1)))
		if sibling.nbytes()+updated.nbytes()-HEADER <= BTREE_PAGE_SIZE {
			return +1, sibling
		}
	}
	return 0, BNode{}
}

func treeDelete(tree *BTree, node BNode, key []byte) BNode {
	idx := nodeLookupLE(node, key)
	switch node.btype() {
	case BNODE_LEAF:
		if !bytes.Equal(key, node.getKey(idx)) {
			return BNode{}
		}
		newNode := BNode(make([]byte, BTREE_PAGE_SIZE))
		leafDelete(newNode, node, idx)
		return newNode
	case BNODE_NODE:
		return nodeDelete(tree, node, idx, key)
	default:
		panic("bad node type")
	}
}

func nodeDelete(tree *BTree, node BNode, idx uint16, key []byte) BNode {
	kptr := node.getPtr(idx)
	updated := treeDelete(tree, tree.get(kptr), key)
	if len(updated) == 0 {
		return BNode{}
	}
	tree.del(kptr)
	newNode := BNode(make([]byte, BTREE_PAGE_SIZE))
	mergeDir, sibling := shouldMerge(tree, node, idx, updated)
	switch {
	case mergeDir < 0:
		merged := BNode(make([]byte, BTREE_PAGE_SIZE))
		nodeMerge(merged, sibling, updated)
		tree.del(node.getPtr(idx - 1))
		nodeReplace2Kid(newNode, node, idx-1, tree.new(merged), merged.getKey(0))
	case mergeDir > 0:
		merged := BNode(make([]byte, BTREE_PAGE_SIZE))
		nodeMerge(merged, updated, sibling)
		tree.del(node.getPtr(idx + 1))
		nodeReplace2Kid(newNode, node, idx, tree.new(merged), merged.getKey(0))
	case mergeDir == 0 && updated.nkeys() == 0:
		assert(node.nkeys() == 1 && idx == 0)
		newNode.setHeader(BNODE_NODE, 0)
	case mergeDir == 0 && updated.nkeys() > 0:
		nodeReplaceKidN(tree, newNode, node, idx, updated)
	}
	return newNode
}

// Delete removes a key from the tree. Returns true if the key existed.
func (tree *BTree) Delete(key []byte) bool {
	if tree.root == 0 {
		return false
	}
	updated := treeDelete(tree, tree.get(tree.root), key)
	if len(updated) == 0 {
		return false
	}
	tree.del(tree.root)
	if updated.btype() == BNODE_NODE && updated.nkeys() == 1 {
		tree.root = updated.getPtr(0)
	} else {
		tree.root = tree.new(updated)
	}
	return true
}

// Scan iterates all key-value pairs in sorted order
func (tree *BTree) Scan(cb func(key, val []byte)) {
	if tree.root == 0 {
		return
	}
	treeScan(tree, tree.get(tree.root), cb)
}

func treeScan(tree *BTree, node BNode, cb func(key, val []byte)) {
	switch node.btype() {
	case BNODE_LEAF:
		for i := uint16(0); i < node.nkeys(); i++ {
			key := node.getKey(i)
			if len(key) > 0 { // skip sentinel
				cb(key, node.getVal(i))
			}
		}
	case BNODE_NODE:
		for i := uint16(0); i < node.nkeys(); i++ {
			treeScan(tree, tree.get(node.getPtr(i)), cb)
		}
	}
}

func assert(cond bool) {
	if !cond {
		panic("assertion failed")
	}
}
