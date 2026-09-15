// Handler composition: state + choice interaction
// Demonstrates how handler nesting order affects semantics
//

effect ctl choice() : bool

effect state<a>
  fun get() : a
  fun set(x : a) : ()

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

fun xor() : choice bool
  val p = choice()
  val q = choice()
  if p then !q else q

fun surprising() : <choice, state<int>> bool
  val p = choice()
  val i = get()
  set(i + 1)
  if i > 0 && p then xor() else False

// State outside, choice inside: state is SHARED across all branches.
// resume(False) runs fully, mutating state; resume(True) sees the updated state.
fun state-choice() : div (list<bool>, int)
  pstate(0)
    choice-all(surprising)

// Choice outside, state inside: each branch has its OWN fresh state.
fun choice-state() : div list<(bool, int)>
  choice-all
    pstate(0, surprising)

fun main()
  val r1 = state-choice()
  println("state-choice: " ++ r1.show)
  val r2 = choice-state()
  println("choice-state: " ++ r2.show)
