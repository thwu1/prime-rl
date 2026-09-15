import cadquery as cq
r=cq.Workplane('XY').box(100,80,60).faces(">Y").workplane().hole(40)
