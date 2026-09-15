"""
Syscall specifications for kernel verification.

Each function models a kernel syscall as a symbolic state transition:
    (old_state, args...) -> (precondition, new_state)

The precondition is a Z3 boolean formula describing when the syscall
succeeds. The new_state reflects the kernel state after successful
execution. When the precondition is false, the state is unchanged.

These specifications are derived from the Hyperkernel OS kernel's
system call implementations. Some may contain subtle deviations
from the intended security properties.

"""

from kernel_model import *


def spec_alloc_frame(state, pid, from_pn, index, to_pn, perm):
    """
    Allocate a free page as a frame and map it into a page table.

    Converts to_pn from FREE to FRAME, assigns it to pid, and creates
    a page table entry at from_pn[index] pointing to the new frame.

    Parameters:
        state: Current kernel state
        pid: Target process ID (must be current or embryo of current)
        from_pn: Page table page number
        index: Slot index within the page table
        to_pn: Page number to allocate as a frame (must be FREE)
        perm: Permission bits for the new mapping
    """
    precond = z3.And(
        is_pid_valid(pid),
        is_current_or_embryo(state, pid),
        is_pn_valid(from_pn),
        z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_X86_PT),
        z3.Select(state.page_owner, from_pn) == pid,
        is_page_index_valid(index),
        is_pn_valid(to_pn),
        z3.Select(state.page_type, to_pn) == bv(PAGE_TYPE_FREE),
        perm_safe(perm),
        z3.Not(pte_present(z3.Select(z3.Select(state.page_data, from_pn), index))),
    )

    new = state.copy()
    new.page_type = z3.Store(new.page_type, to_pn, bv(PAGE_TYPE_FRAME))
    new.page_owner = z3.Store(new.page_owner, to_pn, pid)
    pfn = state.pages_base_pfn + to_pn
    entry = (pfn << bv(PTE_PFN_SHIFT)) | perm
    inner = z3.Store(z3.Select(new.page_data, from_pn), index, entry)
    new.page_data = z3.Store(new.page_data, from_pn, inner)

    return precond, new


def spec_map_page_desc(state, pid, from_pn, index, n, perm):
    """
    Map a page of the page descriptor table into a process's page table.

    The page descriptor table is a read-only kernel structure occupying
    NPAGES_PAGE_DESC_TABLE pages. The offset n selects which page to map.
    Write permission must be denied to protect the table's integrity.

    Parameters:
        state: Current kernel state
        pid: Target process ID
        from_pn: Page table page number
        index: Slot index within the page table
        n: Offset into the page descriptor table (must be within bounds)
        perm: Permission bits (write must be denied)
    """
    precond = z3.And(
        z3.ULT(n, bv(NPAGES_PAGE_DESC_TABLE + 1)),

        is_pid_valid(pid),
        is_current_or_embryo(state, pid),
        is_pn_valid(from_pn),
        z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_X86_PT),
        z3.Select(state.page_owner, from_pn) == pid,
        is_page_index_valid(index),
        perm_safe(perm),
        z3.Not(pte_writable(perm)),
        z3.Not(pte_present(z3.Select(z3.Select(state.page_data, from_pn), index))),
    )

    new = state.copy()
    pfn = state.page_desc_base_pfn + n
    entry = (pfn << bv(PTE_PFN_SHIFT)) | perm
    inner = z3.Store(z3.Select(new.page_data, from_pn), index, entry)
    new.page_data = z3.Store(new.page_data, from_pn, inner)

    return precond, new


def spec_free_frame(state, from_pn, index, to_pn):
    """
    Free a frame page and clear its page table mapping.

    Releases to_pn back to FREE state and clears the page table entry
    at from_pn[index]. Both the page table page and the frame being
    freed must be owned by the current process.

    Parameters:
        state: Current kernel state
        from_pn: Page table page number (must be owned by current)
        index: Slot index within the page table (must have a present entry)
        to_pn: Frame page number to free (must be owned by current)
    """
    precond = z3.And(
        is_pn_valid(from_pn),
        z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_X86_PT),
        z3.Select(state.page_owner, from_pn) == state.current,
        is_page_index_valid(index),
        is_pn_valid(to_pn),
        z3.Select(state.page_type, to_pn) == bv(PAGE_TYPE_FRAME),
        z3.Select(state.page_owner, from_pn) == state.current,
        pte_present(z3.Select(z3.Select(state.page_data, from_pn), index)),
    )

    new = state.copy()
    new.page_type = z3.Store(new.page_type, to_pn, bv(PAGE_TYPE_FREE))
    new.page_owner = z3.Store(new.page_owner, to_pn, bv(0))
    inner = z3.Store(z3.Select(new.page_data, from_pn), index, bv(0))
    new.page_data = z3.Store(new.page_data, from_pn, inner)

    return precond, new


def spec_protect_frame(state, pt, index, frame, perm):
    """
    Update permissions on an existing frame mapping in a page table.

    Modifies the page table entry at pt[index] to use the new permission
    bits while keeping the same physical frame mapping. The caller must
    own both the page table page and the frame. The index must be valid
    and point to an existing mapping of the specified frame.

    Parameters:
        state: Current kernel state
        pt: Page table page number
        index: Slot index within the page table (must be valid, < 512)
        frame: Frame page number that the entry maps to
        perm: New permission bits
    """
    pfn = state.pages_base_pfn + frame

    precond = z3.And(
        is_pn_valid(pt),
        z3.Select(state.page_type, pt) == bv(PAGE_TYPE_X86_PT),
        z3.Select(state.page_owner, pt) == state.current,
        is_pn_valid(frame),
        z3.Select(state.page_type, frame) == bv(PAGE_TYPE_FRAME),
        z3.Select(state.page_owner, frame) == state.current,
        pte_present(z3.Select(z3.Select(state.page_data, pt), index)),
        z3.Extract(63, 40, pfn) == z3.BitVecVal(0, 24),
        z3.Extract(39, 0, pfn) == z3.Extract(51, 12,
            z3.Select(z3.Select(state.page_data, pt), index)),
        perm_safe(perm),
    )

    new = state.copy()
    entry = (pfn << bv(PTE_PFN_SHIFT)) | perm
    inner = z3.Store(z3.Select(new.page_data, pt), index, entry)
    new.page_data = z3.Store(new.page_data, pt, inner)

    return precond, new


def spec_map_pci_page(state, pid, from_pn, index, n, perm):
    """
    Map a page of the PCI device table into a process's page table.

    The device table is read-only from user space and occupies
    NPAGES_DEVICES pages. Write permission is denied to prevent
    corruption of device state.

    Parameters:
        state: Current kernel state
        pid: Target process ID
        from_pn: Page table page number
        index: Slot index within the page table
        n: Offset into the device table (must be within bounds)
        perm: Permission bits (write must be denied)
    """
    precond = z3.And(
        z3.ULT(n, bv(NPAGES_DEVICES)),

        is_pid_valid(pid),
        is_current_or_embryo(state, pid),
        is_pn_valid(from_pn),
        z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_X86_PT),
        z3.Select(state.page_owner, from_pn) == pid,
        is_page_index_valid(index),
        perm_safe(perm),
        z3.Not(pte_writable(perm)),
        z3.Not(pte_present(z3.Select(z3.Select(state.page_data, from_pn), index))),
    )

    new = state.copy()
    pfn = state.devices_base_pfn + n
    entry = (pfn << bv(PTE_PFN_SHIFT)) | perm
    inner = z3.Store(z3.Select(new.page_data, from_pn), index, entry)
    new.page_data = z3.Store(new.page_data, from_pn, inner)

    return precond, new


def spec_copy_frame(state, from_pn, pid, to_pn):
    """
    Copy the contents of one frame to another.

    Copies all data from from_pn to to_pn. The source frame must be
    owned by the current process. The destination frame must be owned
    by pid (which must be current or an embryo of current).

    Parameters:
        state: Current kernel state
        from_pn: Source frame page number (must be owned by current)
        pid: Owner of the destination frame
        to_pn: Destination frame page number (must be owned by pid)
    """
    precond = z3.And(
        is_pn_valid(from_pn),
        z3.Select(state.page_type, from_pn) == bv(PAGE_TYPE_FRAME),
        z3.Select(state.page_owner, to_pn) == state.current,

        is_pid_valid(pid),
        is_current_or_embryo(state, pid),
        is_pn_valid(to_pn),
        z3.Select(state.page_type, to_pn) == bv(PAGE_TYPE_FRAME),
        z3.Select(state.page_owner, to_pn) == pid,
    )

    new = state.copy()
    new.page_data = z3.Store(new.page_data, to_pn, z3.Select(state.page_data, from_pn))

    return precond, new
