// Three-handler composition: reader + state + choice
// Demonstrates how nesting order determines shared vs. local state semantics
// when combined with a constant reader value.
//

effect ctl choice() : bool

effect state<a>
  fun get() : a
  fun set(x : a) : ()

effect val reader : int

fun choice-all(action : () -> <choice|e> a) : e list<a>
  with handler
    return(x) [x]
    ctl choice() resume(False) ++ resume(True)
  action()

fun pstate(init : a, action : () -> <state<a>|e> b) : e (b, a)
  var st := init
  with handler
    return(x)  (x, st)
    fun get()  st
    fun set(i) st := i
  action()

fun triple() : <choice, state<int>, reader> int
  val r = reader
  val p = choice()
  val s = get()
  set(s + r)
  if p then s + r else s

// Shared state: reader(10) { pstate(0) { choice-all { triple() } } }
fun compose-shared() : div (list<int>, int)
  with val reader = 10
  pstate(0)
    choice-all(triple)

// Local state: reader(10) { choice-all { pstate(0) { triple() } } }
fun compose-local() : div list<(int, int)>
  with val reader = 10
  choice-all
    pstate(0, triple)

fun main()
  val r1 = compose-shared()
  println("shared: " ++ r1.show)
  val r2 = compose-local()
  println("local: " ++ r2.show)
