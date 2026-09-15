import cadquery as cq
w0=cq.Workplane('XY',origin=(0,0,0))
r=w0.sketch().segment((-60,-50),(60,-50)).segment((60,10)).segment((20,10)).segment((20,50)).segment((-60,50)).close().assemble().finalize().extrude(40)
