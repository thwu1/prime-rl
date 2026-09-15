/*
 * BSP operations: partition side test, angle computation,
 * subsector location, and front-to-back traversal.
 */


#ifndef BSP_H
#define BSP_H

#include "fixed_math.h"
#include "wad_reader.h"

#define SLOPERANGE  2048

void    bsp_set_data(node_t *nodes, int num_nodes,
                     subsector_t *subsectors, int num_subsectors);

int     SlopeDiv(unsigned int num, unsigned int den);
int     R_PointOnSide(fixed_t x, fixed_t y, node_t *node);
angle_t R_PointToAngle2(fixed_t x1, fixed_t y1, fixed_t x2, fixed_t y2);

int     bsp_locate(fixed_t x, fixed_t y);
int     bsp_traverse(fixed_t x, fixed_t y, int *output, int max_output);

#endif /* BSP_H */
