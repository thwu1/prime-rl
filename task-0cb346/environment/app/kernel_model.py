"""
Simplified kernel state model for formal verification using Z3.

Models an OS kernel's state using Z3 arrays and bitvectors, based on the
Hyperkernel verification framework. Supports symbolic reasoning about
page tables, process metadata, and permission structures.

"""

import z3

# ============================================================
# Constants
# ============================================================

NPAGE = 8192                    # Maximum number of physical pages
NPROC = 64                     # Maximum number of processes
PAGE_SIZE = 4096                # Page size in bytes
NPAGES_PAGE_DESC_TABLE = 64     # Pages occupied by page descriptor table
NPAGES_DEVICES = 2             # Pages occupied by device table

# Page types
PAGE_TYPE_FREE = 0
PAGE_TYPE_RESERVED = 1
PAGE_TYPE_PROC_DATA = 2
PAGE_TYPE_FRAME = 3
PAGE_TYPE_X86_PML4 = 4
PAGE_TYPE_X86_PDPT = 5
PAGE_TYPE_X86_PD = 6
PAGE_TYPE_X86_PT = 7

# Process states
PROC_UNUSED = 0
PROC_EMBRYO = 1
PROC_RUNNABLE = 2
PROC_RUNNING = 3
PROC_SLEEPING = 4
PROC_ZOMBIE = 5

# Page table entry permission bits
PTE_P = 1 << 0      # Present
PTE_W = 1 << 1      # Writable
PTE_U = 1 << 2      # User-accessible
PTE_PWT = 1 << 3    # Write-through
PTE_PCD = 1 << 4    # Cache disable
PTE_AVL = (1 << 9) | (1 << 10) | (1 << 11)  # Available for software use
PTE_NX = 1 << 63    # No-execute
PTE_PERM_MASK = PTE_P | PTE_W | PTE_U | PTE_PWT | PTE_PCD | PTE_AVL | PTE_NX
PTE_PFN_SHIFT = 12  # Physical frame number starts at bit 12

# Z3 bitvector sort
BV64 = z3.BitVecSort(64)


def bv(val):
    """Create a 64-bit Z3 bitvector constant."""
    return z3.BitVecVal(val, 64)


class KernelState:
    """
    Symbolic kernel state for specification verification.

    State components:
    - page_type[pn]: Type of each page (FREE, FRAME, X86_PT, etc.)
    - page_owner[pn]: Process ID that owns each page
    - page_data[pn][idx]: Data stored in page pn at slot idx
    - proc_state[pid]: State of each process (UNUSED, EMBRYO, RUNNING, etc.)
    - proc_ppid[pid]: Parent PID of each process
    - current: PID of the currently executing process
    - pages_base_pfn: Physical frame number base for the pages array
    - page_desc_base_pfn: PFN base for the page descriptor table
    - devices_base_pfn: PFN base for the device table
    """

    def __init__(self, prefix=""):
        p = prefix
        self.page_type = z3.Array(f'{p}pg_type', BV64, BV64)
        self.page_owner = z3.Array(f'{p}pg_owner', BV64, BV64)
        self.page_data = z3.Array(f'{p}pg_data', BV64, z3.ArraySort(BV64, BV64))
        self.proc_state = z3.Array(f'{p}proc_st', BV64, BV64)
        self.proc_ppid = z3.Array(f'{p}proc_ppid', BV64, BV64)
        self.current = z3.BitVec(f'{p}current', 64)
        self.pages_base_pfn = z3.BitVec(f'{p}pages_pfn', 64)
        self.page_desc_base_pfn = z3.BitVec(f'{p}pdesc_pfn', 64)
        self.devices_base_pfn = z3.BitVec(f'{p}dev_pfn', 64)

    def copy(self):
        """Create a shallow copy sharing all Z3 expressions."""
        ns = KernelState.__new__(KernelState)
        ns.page_type = self.page_type
        ns.page_owner = self.page_owner
        ns.page_data = self.page_data
        ns.proc_state = self.proc_state
        ns.proc_ppid = self.proc_ppid
        ns.current = self.current
        ns.pages_base_pfn = self.pages_base_pfn
        ns.page_desc_base_pfn = self.page_desc_base_pfn
        ns.devices_base_pfn = self.devices_base_pfn
        return ns


# ============================================================
# Predicate helpers
# ============================================================

def is_pid_valid(pid):
    """PID must be in range (0, NPROC)."""
    return z3.And(z3.UGT(pid, bv(0)), z3.ULT(pid, bv(NPROC)))


def is_pn_valid(pn):
    """Page number must be in range [0, NPAGE)."""
    return z3.ULT(pn, bv(NPAGE))


def is_page_index_valid(index):
    """Page table index must be in range [0, 512)."""
    return z3.ULT(index, bv(512))


def is_current_or_embryo(state, pid):
    """PID is either the current process or an embryo child of current."""
    return z3.Or(
        pid == state.current,
        z3.And(
            z3.Select(state.proc_ppid, pid) == state.current,
            z3.Select(state.proc_state, pid) == bv(PROC_EMBRYO)
        )
    )


def pte_present(entry):
    """Check if PTE has the Present bit set."""
    return entry & bv(PTE_P) != bv(0)


def pte_writable(perm):
    """Check if permissions include write access."""
    return perm & bv(PTE_W) != bv(0)


def perm_safe(perm):
    """Check permissions have no unsafe bits and the Present bit is set."""
    mask_inv = ~PTE_PERM_MASK & ((1 << 64) - 1)
    return z3.And(
        perm & bv(mask_inv) == bv(0),
        perm & bv(PTE_P) != bv(0)
    )
