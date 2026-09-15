# Unreachable code after constant condition resolution
function target():
  entry:
    a = 10
    b = 5
    cond = gt a b
    jz cond else_path
    result = add a b
    jump done
  else_path:
    result = 0
    jump done
  done:
    return result
