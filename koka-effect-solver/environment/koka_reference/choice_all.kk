// Choice-all handler with multi-shot resume
// Demonstrates: resume(False) ++ resume(True) semantics
//

effect ctl choice() : bool

fun xor() : choice bool
  val p = choice()
  val q = choice()
  if p then !q else q

fun choice-all(action : () -> <choice|e> a) : e list<a>
  with handler
    return(x)    [x]
    ctl choice() resume(False) ++ resume(True)
  action()

fun main()
  val results = choice-all(xor)
  results.foreach fn(b)
    println(b.show)
