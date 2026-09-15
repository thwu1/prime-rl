#ifndef GEOMETRY_H
#define GEOMETRY_H


struct TrapezoidalChannel {
    double bottom_width;  // m
    double side_slope;    // H:V ratio (e.g., 2.0 means 2H:1V)
    double manning_n;     // Manning's roughness coefficient
    double bed_slope;     // m/m

    double area(double depth) const;
    double wetted_perimeter(double depth) const;
    double top_width(double depth) const;
    double hydraulic_radius(double depth) const;
    double discharge(double depth) const;
    double normal_depth(double Q) const;
    double wave_celerity(double Q) const;
};

#endif
