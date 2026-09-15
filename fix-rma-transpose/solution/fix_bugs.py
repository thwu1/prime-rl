#!/usr/bin/env python3
"""Fix all four bugs in rma_transpose.c"""

with open('/app/rma_transpose.c', 'r') as f:
    code = f.read()

# Bug 1: Window displacement unit must be sizeof(double), not 1.
# With disp_unit=1, target displacements in MPI_Put are interpreted
# as byte offsets rather than element offsets, causing all data to
# land at wrong positions.
code = code.replace(
    '1,   /* displacement unit */',
    'sizeof(double),   /* displacement unit */'
)

# Bug 2: MPI_Type_vector stride must be N (the row length of the
# local matrix), not BS. The vector type describes a BS x BS block
# within a BS x N row-major matrix; consecutive rows are N elements
# apart, not BS.
code = code.replace(
    'MPI_Type_vector(BS, BS, BS, MPI_DOUBLE',
    'MPI_Type_vector(BS, BS, N, MPI_DOUBLE'
)

# Bug 3: Block extraction must transpose the sub-block. The indices
# into tmp must be swapped: tmp[c*BS+r] stores row c, col r of the
# transposed block, which is element [r][c] of the original block.
code = code.replace(
    'tmp[r * BS + c] = local_A[r * N + j * BS + c]',
    'tmp[c * BS + r] = local_A[r * N + j * BS + c]'
)

# Bug 4: Target displacement must be rank*BS, not j*BS. The displacement
# identifies where in the target's matrix the source rank's data belongs:
# columns [rank*BS .. rank*BS+BS-1]. Using j*BS places data at the
# target's own block-column index, which is wrong.
code = code.replace(
    'j, j * BS, 1, target_blk_type',
    'j, rank * BS, 1, target_blk_type'
)

with open('/app/rma_transpose.c', 'w') as f:
    f.write(code)

print("All four bugs fixed.")
