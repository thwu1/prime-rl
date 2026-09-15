 *
 * K&R-style heap allocator.
 * Uses a static array as the backing store with an sbrk-like
 * bump allocator feeding a coalescing free-list.
 */
#include "malloc.h"
#include <stdint.h>

typedef long Align;

union header {
	struct {
		union header *ptr;
		unsigned int size;   /* in units of sizeof(Header) */
	} s;
	Align x;                /* force alignment */
};

typedef union header Header;

#define HEAP_SIZE 32768 /* bytes — must cover 4 thread stacks + headers */

static unsigned char heap[HEAP_SIZE];
static unsigned char *program_break = heap;

static Header base;
static Header *freep = 0;

static void *sbrk(unsigned int nbytes)
{
	if (program_break + nbytes >= heap &&
	    program_break + nbytes < heap + HEAP_SIZE) {
		unsigned char *prev = program_break;
		program_break += nbytes;
		return (void *)prev;
	}
	return (void *)-1;
}

void free(void *ap)
{
	Header *bp, *p;

	if (!ap)
		return;

	bp = (Header *)ap - 1;

	for (p = freep; !(bp > p && bp < p->s.ptr); p = p->s.ptr) {
		if (p >= p->s.ptr && (bp > p || bp < p->s.ptr))
			break;
	}

	/* Coalesce with upper neighbour */
	if (bp + bp->s.size == p->s.ptr) {
		bp->s.size += p->s.ptr->s.size;
		bp->s.ptr = p->s.ptr->s.ptr;
	} else {
		bp->s.ptr = p->s.ptr;
	}

	/* Coalesce with lower neighbour */
	if (p + p->s.size == bp) {
		p->s.size += bp->s.size;
		p->s.ptr = bp->s.ptr;
	} else {
		p->s.ptr = bp;
	}

	freep = p;
}

void *malloc(unsigned int nbytes)
{
	Header *p, *prevp;
	unsigned int nunits;
	void *cp;

	nunits = (nbytes + sizeof(Header) - 1) / sizeof(Header) + 1;

	if ((prevp = freep) == 0) {
		base.s.ptr = freep = prevp = &base;
		base.s.size = 0;
	}

	for (p = prevp->s.ptr; ; prevp = p, p = p->s.ptr) {
		if (p->s.size >= nunits) {
			if (p->s.size == nunits) {
				prevp->s.ptr = p->s.ptr;
			} else {
				p->s.size -= nunits;
				p += p->s.size;
				p->s.size = nunits;
			}
			freep = prevp;
			return (void *)(p + 1);
		}

		if (p == freep) {
			cp = sbrk(nunits * sizeof(Header));
			if (cp == (void *)-1)
				return 0;
			p = (Header *)cp;
			p->s.size = nunits;
			free((void *)(p + 1));
			p = freep;
		}
	}
}
