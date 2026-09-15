#include "solver.h"


// ---------------------------------------------------------------
// Free-outflow boundary at the south edge (row nrows).
// Propagates the last interior y-flux to the boundary interface,
// allowing water to exit the domain when flowing southward.
// ---------------------------------------------------------------
void enforce_outflow_boundary(Grid& grid)
{
    int nc = grid.ncols, nr = grid.nrows;
    for (int i = 0; i < nc; i++) {
        // Mirror the interior flux to impose the boundary condition
        double q_interior = grid.Qy[qy_idx(nr - 1, i, nc)];
        grid.Qy[qy_idx(nr, i, nc)] = -q_interior;
    }
}
