import cadquery as cq
b1=cq.Workplane('XY').box(60,40,30)
b2=cq.Workplane('XY',origin=(0,0,10)).box(40,40,20)
r=b1.union(b2)
