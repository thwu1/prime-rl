# Security Policy: Kernel Specification Invariants

Each invariant below defines a security property that applicable syscall
specifications must enforce. An invariant is *applicable* to a specification
if the specification operates on the resources or structures that the
invariant governs. A specification is **SOUND** with respect to an invariant
if, whenever the specification's precondition is satisfied, the invariant
holds. A specification is **VULNERABLE** if there exist concrete inputs
satisfying the precondition for which the invariant fails.

Not all invariants apply to all specifications. Determine applicability from
each specification's semantics and the resources it manipulates.

## S1: Table Bounds Safety

Every syscall that maps a page from a kernel-internal table (page descriptor
table or device table) into a process's address space must enforce that the
table offset is strictly less than the table's declared size constant. The
page descriptor table occupies `NPAGES_PAGE_DESC_TABLE` pages; the device
table occupies `NPAGES_DEVICES` pages. An offset equal to the table size is
out-of-bounds (valid offsets are `0` through `size - 1`).

## S2: Complete Operand Ownership Verification

Every syscall that modifies, frees, or copies page contents must verify
ownership of *every* distinct page operand involved in the operation.
Checking ownership of one operand does not substitute for checking a
different operand. If the operation semantics require that page X is owned
by the current process, the precondition must contain an explicit
`page_owner[X] == current` check for page X specifically — not a check on
some other page Y that happens to use a similar variable name or position
in the argument list.

## S3: Page Table Index Validity

Every syscall that reads or writes a page table entry by index must validate
that the index falls within x86-64 page table bounds (0 <= index < 512) in
its precondition. x86-64 page tables have exactly 512 entries spanning a
4 KB page with 8-byte entries; any index >= 512 accesses memory beyond the
page table boundary.

## S4: Read-Only Mapping Integrity

Every syscall that maps kernel-internal read-only structures (page descriptor
table, device table) must deny write permission by verifying that the
`PTE_W` bit is not set in the permission argument.
