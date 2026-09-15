# Diamond-shaped CFG: tests intersection merge for available expressions
method diamond()
  a = 1
  b = 2
  c = a + b
  d = a * b
  if a > b goto right
  e = c + d
  f = a + b
  goto done
right:
  e = c - d
  f = a + b
done:
  g = e + f
  h = a + b
  return h
