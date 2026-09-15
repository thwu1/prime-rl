import cadquery as cq

# L-shaped bracket profile
pts = [
    (0, 0),
    (30, 0),
    (30, 5),
    (5, 5),
    (5, 20),
    (0, 20),
]
result = cq.Workplane("XY").polyline(pts).close().extrude(10)
cq.exporters.export(result, "output.stl")
