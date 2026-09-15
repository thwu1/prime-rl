import cadquery as cq
w0=cq.Workplane('XY',origin=(0,0,0))
w1=cq.Workplane('XY',origin=(0,0,80))
r=w0.box(100,60,40).union(w1.box(40,40,30))
