FUNC main:
entry:
  a = 10
  b = 20
  c = a + b
  d = a + b
  IF c GOTO loop
  GOTO end
loop:
  e = c + d
  a = a - 1
  f = a + b
  c = a + b
  IF a GOTO loop
  GOTO end
end:
  g = 0
  h = g + 1
  RETURN c
ENDFUNC
