# Diamond-shaped CFG with a constant condition making one path unreachable
function target():
  entry:
    x = 10
    cond = mod x 2
    jz cond even_path
  odd_path:
    result = add x 1
    jump merge
  even_path:
    result = sub x 1
    jump merge
  merge:
    return result
