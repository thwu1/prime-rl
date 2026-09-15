# Branching with merge: tests union vs intersection at join point
method branch()
  a = 5
  b = 3
  c = a + b
  if a > b goto right
  a = 7
  d = a - b
  goto merge
right:
  d = b
merge:
  e = a + b
  return e
