# Security Properties for Kernel Specification Verification

Each property below defines a security invariant that a correct syscall
specification must satisfy. A property is **VIOLATED** if there exist
concrete inputs for which the specification's precondition is satisfiable
but the property does not hold. A property **HOLDS** if no such inputs
exist (i.e., the conjunction of the precondition and the negation of the
property is unsatisfiable in Z3).

For each property, you must determine HOLDS or VIOLATED. For violations,
extract a concrete counterexample from the Z3 model demonstrating inputs
that satisfy the precondition while violating the property.

---

## P1: map_page_desc — Bounds Safety

**Specification:** `spec_map_page_desc`
**Property:** When the specification's precondition is satisfied, the page
descriptor table offset `n` must be strictly less than
`NPAGES_PAGE_DESC_TABLE` (64).

Rationale: The page descriptor table occupies exactly 64 pages. An offset
of 64 or more would access memory beyond the table boundary, potentially
exposing adjacent kernel data structures to user-space mapping.

---

## P2: map_page_desc — Write Permission Denied

**Specification:** `spec_map_page_desc`
**Property:** When the specification's precondition is satisfied, the
permission bits `perm` must not include `PTE_W` (the write bit, value 2).

Rationale: The page descriptor table is a read-only kernel data structure.
Write mappings would allow user-space corruption of page metadata.

---

## P3: free_frame — Target Ownership

**Specification:** `spec_free_frame`
**Property:** When the specification's precondition is satisfied, the frame
being freed (`to_pn`) must be owned by the current process. Formally:
`page_owner[to_pn] == current`.

Rationale: Freeing a frame owned by another process enables use-after-free
and double-free vulnerabilities that can compromise kernel memory safety.

---

## P4: protect_frame — Index Validity

**Specification:** `spec_protect_frame`
**Property:** When the specification's precondition is satisfied, the page
table index `index` must be a valid page table index: `index < 512`.

Rationale: x86 page tables have exactly 512 entries (covering a 4KB page
with 8-byte entries). An out-of-bounds index corrupts memory adjacent to
the page table, which typically contains other kernel data structures.

---

## P5: map_pci_page — Bounds Safety

**Specification:** `spec_map_pci_page`
**Property:** When the specification's precondition is satisfied, the
device table offset `n` must be strictly less than `NPAGES_DEVICES` (2).

Rationale: The device table occupies exactly 2 pages. Out-of-bounds access
would map arbitrary kernel memory into user space.

---

## P6: map_pci_page — Write Permission Denied

**Specification:** `spec_map_pci_page`
**Property:** When the specification's precondition is satisfied, the
permission bits `perm` must not include `PTE_W`.

Rationale: Device table mappings are read-only from user space. Write
access could corrupt device state and destabilize the system.

---

## P7: copy_frame — Source Ownership

**Specification:** `spec_copy_frame`
**Property:** When the specification's precondition is satisfied, the
source frame (`from_pn`) must be owned by the current process. Formally:
`page_owner[from_pn] == current`.

Rationale: Copying from a frame not owned by the current process is an
information disclosure vulnerability — it allows reading another
process's private memory.

---

## P8: alloc_frame — Target Is Free

**Specification:** `spec_alloc_frame`
**Property:** When the specification's precondition is satisfied, the
target page (`to_pn`) must be of type `PAGE_TYPE_FREE` (value 0).

Rationale: Allocating a page that is already in use would corrupt existing
memory mappings and violate type safety of the page management system.
