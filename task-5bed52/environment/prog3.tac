FUNC nested:
entry:
  i = 10
  sum = 0
  GOTO outer_check
outer_check:
  IF i GOTO outer_body
  GOTO done
outer_body:
  j = i
  t1 = i * i
  GOTO inner_check
inner_check:
  IF j GOTO inner_body
  GOTO outer_next
inner_body:
  t2 = i * i
  sum = sum + t2
  j = j - 1
  dead1 = j + sum
  dead2 = dead1 * 2
  GOTO inner_check
outer_next:
  i = i - 1
  GOTO outer_check
done:
  RETURN sum
ENDFUNC
