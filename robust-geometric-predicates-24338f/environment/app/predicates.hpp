#ifndef PREDICATES_HPP
#define PREDICATES_HPP

// Robust geometric predicates using adaptive-precision expansion arithmetic.
//
// orient2d(pa, pb, pc):
//   Positive if pa,pb,pc are counterclockwise; negative if clockwise; zero if collinear.
//   Each point is double[2].
//
// orient3d(pa, pb, pc, pd):
//   Positive if pd lies below the oriented plane through pa,pb,pc (counterclockwise
//   when viewed from above); negative if above; zero if coplanar.
//   Each point is double[3].
//
// incircle(pa, pb, pc, pd):
//   Positive if pd lies inside the circle through pa,pb,pc (counterclockwise order);
//   negative if outside; zero if cocircular.
//   Each point is double[2].
//
// insphere(pa, pb, pc, pd, pe):
//   Positive if pe lies inside the sphere through pa,pb,pc,pd (positive orientation);
//   negative if outside; zero if cospherical.
//   Each point is double[3].

void predicates_init();

double orient2d(const double *pa, const double *pb, const double *pc);
double orient3d(const double *pa, const double *pb, const double *pc, const double *pd);
double incircle(const double *pa, const double *pb, const double *pc, const double *pd);
double insphere(const double *pa, const double *pb, const double *pc, const double *pd, const double *pe);

#endif // PREDICATES_HPP
