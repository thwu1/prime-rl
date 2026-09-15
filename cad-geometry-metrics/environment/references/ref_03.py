import cadquery as cq

# L-shaped bracket profile - different proportions from candidate
pts = [
    (0, 0),
    (25, 0),
    (25, 5),
    (5, 5),
    (5, 25),
    (0, 25),
]
result = cq.Workplane("XY").polyline(pts).close().extrude(10)
cq.exporters.export(result, "output.stl")
