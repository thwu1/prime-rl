// N-Queens solver using algebraic effects
// Demonstrates: multi-shot resume for constraint solving
//

effect ctl pick(n : int) : int
effect ctl abort() : a

fun solutions(action : () -> <pick, abort|e> a) : e list<a>
  with handler
    return(x) [x]
    ctl abort() []
    ctl pick(n)
      list(1, n).flatmap fn(i)
        resume(i)
  action()

fun safe(queen : int, placed : list<int>, dist : int) : bool
  match placed
    Nil -> True
    Cons(q, rest) ->
      if queen == q || queen == q + dist || queen == q - dist
        then False
        else safe(queen, rest, dist + 1)

fun queens(n : int) : <pick, abort> list<int>
  place(n, n, [])

fun place(n : int, remaining : int, placed : list<int>) : <pick, abort> list<int>
  if remaining <= 0 then placed.reverse
  else
    val row = pick(n)
    if safe(row, placed, 1) then place(n, remaining - 1, Cons(row, placed))
    else abort()

fun main()
  val sols5 = solutions{ queens(5) }
  println("queens(5): " ++ sols5.length.show ++ " solutions")
  println("first: " ++ sols5.head.unjust.map(show).join(","))
  val sols8 = solutions{ queens(8) }
  println("queens(8): " ++ sols8.length.show ++ " solutions")
  println("first: " ++ sols8.head.unjust.map(show).join(","))
