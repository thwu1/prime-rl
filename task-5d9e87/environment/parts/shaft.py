import cadquery as cq
r=(cq.Workplane('XY').circle(19).extrude(30)
   .faces(">Z").workplane().circle(12).extrude(40))
