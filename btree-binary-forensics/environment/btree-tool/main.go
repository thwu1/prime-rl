package main

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
)

const (
	PageSize      = 4096
	BNodeInternal = 1
	BNodeLeaf     = 2
	FreeListCap   = (PageSize - 8) / 8
)

var Signature = []byte("BYO_DB_MAGIC_V01")

type Meta struct {
	RootPtr    uint64
	PagesUsed  uint64
	FLHeadPage uint64
	FLHeadSeq  uint64
	FLTailPage uint64
	FLTailSeq  uint64
}

type Violation struct {
	Code   string `json:"code"`
	Page   int    `json:"page"`
	Detail string `json:"detail"`
}

func readPages(path string) ([][]byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	n := len(data) / PageSize
	pages := make([][]byte, n)
	for i := 0; i < n; i++ {
		pages[i] = data[i*PageSize : (i+1)*PageSize]
	}
	return pages, nil
}

func parseMeta(page []byte) (*Meta, error) {
	for i := 0; i < 16; i++ {
		if page[i] != Signature[i] {
			return nil, fmt.Errorf("invalid signature at byte %d", i)
		}
	}
	return &Meta{
		RootPtr:    binary.LittleEndian.Uint64(page[16:]),
		PagesUsed:  binary.LittleEndian.Uint64(page[24:]),
		FLHeadPage: binary.LittleEndian.Uint64(page[32:]),
		FLHeadSeq:  binary.LittleEndian.Uint64(page[40:]),
		FLTailPage: binary.LittleEndian.Uint64(page[48:]),
		FLTailSeq:  binary.LittleEndian.Uint64(page[56:]),
	}, nil
}

func getNodeType(page []byte) uint16 {
	return binary.LittleEndian.Uint16(page[0:])
}

func getNKeys(page []byte) uint16 {
	return binary.LittleEndian.Uint16(page[2:])
}

func getPtr(page []byte, idx int) uint64 {
	return binary.LittleEndian.Uint64(page[4+8*idx:])
}

func getKey(page []byte, idx int) string {
	nkeys := int(getNKeys(page))
	kvDataStart := 4 + 8*nkeys + 2*nkeys
	var kvPos int
	if idx == 0 {
		kvPos = kvDataStart
	} else {
		off := int(binary.LittleEndian.Uint16(page[4+8*nkeys+2*(idx-1):]))
		kvPos = kvDataStart + off
	}
	klen := int(binary.LittleEndian.Uint16(page[kvPos:]))
	return string(page[kvPos+4 : kvPos+4+klen])
}

func verify(pages [][]byte, meta *Meta) []Violation {
	var violations []Violation
	reachable := make(map[int]bool)

	var walkTree func(pageNum int)
	walkTree = func(pageNum int) {
		if pageNum < 0 || pageNum >= len(pages) || reachable[pageNum] {
			return
		}
		reachable[pageNum] = true
		ntype := getNodeType(pages[pageNum])
		nkeys := int(getNKeys(pages[pageNum]))

		if ntype == BNodeInternal {
			for i := 0; i < nkeys; i++ {
				childPtr := int(getPtr(pages[pageNum], i))
				if childPtr <= 0 || childPtr >= len(pages) {
					violations = append(violations, Violation{
						Code:   "INVALID_CHILD_PTR",
						Page:   pageNum,
						Detail: fmt.Sprintf("ptr[%d]=%d out of range [1,%d)", i, childPtr, len(pages)),
					})
					continue
				}
				parentKey := getKey(pages[pageNum], i)
				childFirstKey := getKey(pages[childPtr], 0)
				if parentKey != childFirstKey {
					violations = append(violations, Violation{
						Code:   "KEY_BOUNDARY_MISMATCH",
						Page:   pageNum,
						Detail: fmt.Sprintf("key[%d]=%q does not match child page %d first_key=%q", i, parentKey, childPtr, childFirstKey),
					})
				}
				walkTree(childPtr)
			}
		} else if ntype == BNodeLeaf {
			for i := 1; i < nkeys; i++ {
				prev := getKey(pages[pageNum], i-1)
				curr := getKey(pages[pageNum], i)
				if prev >= curr {
					violations = append(violations, Violation{
						Code:   "UNSORTED_KEYS",
						Page:   pageNum,
						Detail: fmt.Sprintf("key[%d]=%q >= key[%d]=%q", i-1, prev, i, curr),
					})
				}
			}
		}
	}

	walkTree(int(meta.RootPtr))

	// Walk free list and cross-reference with reachable pages
	curPage := int(meta.FLHeadPage)
	seq := meta.FLHeadSeq
	maxIter := meta.PagesUsed * uint64(FreeListCap)
	var iter uint64

	for seq < meta.FLTailSeq && iter < maxIter {
		idx := seq % uint64(FreeListCap)
		item := int(binary.LittleEndian.Uint64(pages[curPage][8+8*idx:]))

		if item == 0 {
			violations = append(violations, Violation{
				Code:   "FREELIST_REFERENCES_META",
				Page:   curPage,
				Detail: fmt.Sprintf("seq=%d idx=%d references meta page 0", seq, idx),
			})
		} else if item >= int(meta.PagesUsed) {
			violations = append(violations, Violation{
				Code:   "FREELIST_OUT_OF_RANGE",
				Page:   curPage,
				Detail: fmt.Sprintf("seq=%d references page %d >= pages_used %d", seq, item, meta.PagesUsed),
			})
		} else if reachable[item] {
			violations = append(violations, Violation{
				Code:   "DOUBLE_ALLOCATION",
				Page:   item,
				Detail: fmt.Sprintf("page %d is both reachable from tree and freed at seq=%d", item, seq),
			})
		}

		seq++
		if seq < meta.FLTailSeq && seq%uint64(FreeListCap) == 0 {
			nextPtr := int(binary.LittleEndian.Uint64(pages[curPage][:8]))
			curPage = nextPtr
		}
		iter++
	}

	return violations
}

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: %s <command> <database.db>\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Commands: dump-meta, verify\n")
		os.Exit(2)
	}
	cmd := os.Args[1]
	dbPath := os.Args[2]

	pages, err := readPages(dbPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error reading database: %v\n", err)
		os.Exit(1)
	}
	meta, err := parseMeta(pages[0])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing meta page: %v\n", err)
		os.Exit(1)
	}

	switch cmd {
	case "dump-meta":
		fmt.Printf("Root:       page %d\n", meta.RootPtr)
		fmt.Printf("PagesUsed:  %d\n", meta.PagesUsed)
		fmt.Printf("FL Head:    page %d, seq %d\n", meta.FLHeadPage, meta.FLHeadSeq)
		fmt.Printf("FL Tail:    page %d, seq %d\n", meta.FLTailPage, meta.FLTailSeq)

	case "verify":
		violations := verify(pages, meta)
		if len(violations) == 0 {
			fmt.Println("CONSISTENT")
			os.Exit(0)
		}
		for _, v := range violations {
			line, _ := json.Marshal(v)
			fmt.Println(string(line))
		}
		fmt.Printf("\n%d violation(s) found\n", len(violations))
		os.Exit(1)

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", cmd)
		os.Exit(2)
	}
}
