import cadquery as cq

# Box with centered through-hole (diameter 20)
length = 80.0
height = 60.0
thickness = 10.0
center_hole_dia = 20.0

result = (
    cq.Workplane("XY")
    .box(length, height, thickness)
    .faces(">Z")
    .workplane()
    .hole(center_hole_dia)
)
cq.exporters.export(result, "output.stl")
