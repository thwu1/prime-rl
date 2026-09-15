import cadquery as cq
r=(cq.Workplane('XY').circle(50).extrude(12)
   .faces(">Z").workplane()
   .pushPoints([(35,0),(0,35),(-35,0),(0,-35)])
   .hole(8)
   .faces(">Z").workplane()
   .hole(15))
