#ifndef SDF_H
#define SDF_H

double sd_sphere(double px, double py, double pz, double r);
double sd_torus(double px, double py, double pz, double R, double r);
double sd_round_box(double px, double py, double pz,
                    double bx, double by, double bz, double rad);
double sd_octahedron(double px, double py, double pz, double s);
double smin_poly(double d1, double d2, double k);

#endif
