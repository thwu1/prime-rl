FUNC compute:
entry:
  x = 5
  y = 3
  z = x * y
  w = x * y
  IF z GOTO then_b
  GOTO else_b
then_b:
  a = z + 1
  b = x * y
  c = a + b
  GOTO merge
else_b:
  a = z - 1
  b = 0
  c = a + b
  GOTO merge
merge:
  d = x * y
  e = c + d
  result = e + 0
  RETURN result
ENDFUNC
