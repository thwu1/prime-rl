/* Depot Selection MIP for Location-Routing Problem
 *
 * Determines which depots to open and how to assign customers to depots,
 * minimizing setup costs plus estimated routing costs. Routing cost is
 * approximated as 2 * Euclidean distance (round-trip proxy).
 *
 * Complete the TODO sections to make this model functional with glpsol.
 */

set DEPOTS;
set CUSTOMERS;

param setup{d in DEPOTS};
param depot_cap{d in DEPOTS};
param demand{c in CUSTOMERS};
param dist{d in DEPOTS, c in CUSTOMERS};
param max_vehicles;
param vehicle_cap;

var open{d in DEPOTS}, binary;
var assign{d in DEPOTS, c in CUSTOMERS}, binary;

minimize total_cost:
    sum{d in DEPOTS} setup[d] * open[d]
    + sum{d in DEPOTS, c in CUSTOMERS} 2 * dist[d,c] * assign[d,c];

/* Every customer must be assigned to exactly one depot */
s.t. customer_served{c in CUSTOMERS}:
    sum{d in DEPOTS} assign[d,c] = 1;

/* A customer can only be assigned to an open depot */
s.t. depot_link{d in DEPOTS, c in CUSTOMERS}:
    assign[d,c] <= open[d];

/* TODO: Add constraint 'depot_capacity' indexed over DEPOTS.
   The total demand of customers assigned to depot d must not exceed
   depot_cap[d] when d is open. */

/* TODO: Add constraint 'fleet_limit' indexed over DEPOTS.
   The total demand assigned to each open depot must not exceed the
   total carrying capacity of its vehicle fleet: max_vehicles * vehicle_cap. */

solve;

/* TODO: Add output section using GMPL printf.
   Print one line per depot:    DEPOT <index> <1 if open, 0 if closed>
   Print one line per assignment (where assign[d,c] = 1):
                                ASSIGN <customer_index> <depot_index>
   End with: end; */

end;
