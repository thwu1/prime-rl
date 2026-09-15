"""Distance calculation utilities for seismic hazard analysis."""

import math


def horizontal_distance(lon1, lat1, lon2, lat2, km_per_deg):
    """Compute flat-earth horizontal distance between two geographic points.

    Applies a cosine correction on the longitudinal difference to
    account for convergence of meridians at higher latitudes.
    """
    avg_lat = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * math.cos(avg_lat) * km_per_deg
    dy = (lat2 - lat1) * km_per_deg
    return math.sqrt(dx * dx + dy * dy)


def convert_trace_to_local(trace, site_lon, site_lat, km_per_deg):
    """Convert a fault trace from geographic coordinates to local km.

    The local coordinate system is centered at the site location.
    Returns list of (x_km, y_km) tuples.
    """
    tkm = []
    for pt in trace:
        dx = (pt["longitude"] - site_lon) * math.cos(math.radians(site_lat)) * km_per_deg
        dy = (pt["latitude"] - site_lat) * km_per_deg
        tkm.append((dx, dy))
    return tkm


def point_to_segment(px, py, ax, ay, bx, by):
    """Minimum distance from point (px,py) to line segment (ax,ay)-(bx,by)."""
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-10:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = ((px - ax) * dx + (py - ay) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.sqrt((px - qx) ** 2 + (py - qy) ** 2)


def point_to_polyline(px, py, polyline):
    """Minimum distance from a point to a polyline (list of vertices)."""
    min_d = float("inf")
    for i in range(len(polyline) - 1):
        d = point_to_segment(
            px, py,
            polyline[i][0], polyline[i][1],
            polyline[i + 1][0], polyline[i + 1][1],
        )
        if d < min_d:
            min_d = d
    return min_d
