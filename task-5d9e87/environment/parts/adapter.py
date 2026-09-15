import cadquery as cq
r=(cq.Workplane('XY')
   .circle(35).extrude(25)
   .faces(">Z").workplane()
   .circle(20).extrude(20))
