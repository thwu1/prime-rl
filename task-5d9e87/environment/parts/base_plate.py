import cadquery as cq
r=(cq.Workplane('XY').box(120,80,15)
   .faces(">Z").workplane()
   .pushPoints([(40,25),(-40,25),(40,-25),(-40,-25)])
   .hole(8)
   .faces(">Z").workplane()
   .hole(40))
