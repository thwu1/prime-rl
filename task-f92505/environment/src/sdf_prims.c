#include <math.h>
#include "sdf.h"

double sd_sphere(double px, double py, double pz, double r) {
    return sqrt(px*px + py*py + pz*pz) - r;
}

double sd_torus(double px, double py, double pz, double R, double r) {
    double q = sqrt(px*px + pz*pz) - R;
    return fabs(q) - r;
}

double sd_round_box(double px, double py, double pz,
                    double bx, double by, double bz, double rad) {
    double qx = fabs(px) - bx;
    double qy = fabs(py) - by;
    double qz = fabs(pz) - bz;
    double mx = qx > 0.0 ? qx : 0.0;
    double my = qy > 0.0 ? qy : 0.0;
    double mz = qz > 0.0 ? qz : 0.0;
    double outer = sqrt(mx*mx + my*my + mz*mz);
    double inner_xy = qx > qy ? qx : qy;
    double inner = inner_xy > qz ? inner_xy : qz;
    if (inner > 0.0) inner = 0.0;
    return outer + inner - rad;
}

double sd_octahedron(double px, double py, double pz, double s) {
    px = fabs(px);
    py = fabs(py);
    pz = fabs(pz);
    return (px + py + pz - s) * 0.57735027;
}
