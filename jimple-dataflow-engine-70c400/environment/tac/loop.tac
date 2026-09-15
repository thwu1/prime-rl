# Loop with back edge: tests fixed-point convergence
method loop()
  n = 10
  i = 0
  s = 0
header:
  if i >= n goto exit
  t = s + i
  s = t
  u = i + n
  i = u
  goto header
exit:
  return s
