package rstream


// ---------------------------------------------------------------------------
// Pipeline: utilities for connecting emitters, transforms, and receivers.
// ---------------------------------------------------------------------------
object Pipeline {
  def connect[A, B](emitter: Emitter[A], transform: Transform[A, B],
                    receiver: Receiver[B]): Unit =
    receiver.accept(transform.apply(emitter.emit))

  def connectN[A, B](emitter: Emitter[A], transform: Transform[A, B],
                     receiver: Receiver[B], n: Int): Unit =
    (0 until n).foreach(_ => receiver.accept(transform.apply(emitter.emit)))

  def widenEmitter[A, B <: A](emitter: Emitter[A]): Emitter[B] = emitter

  def composeTransforms[A, B, C](t1: Transform[A, B],
                                  t2: Transform[B, C]): Transform[A, C] = ???
}

// ---------------------------------------------------------------------------
// Distributor: sends each value to a list of receivers.
// ---------------------------------------------------------------------------
class Distributor[+A](receivers: List[Receiver[A]]) {
  def send(a: A): Unit = receivers.foreach(_.accept(a))
}

// ---------------------------------------------------------------------------
// TypedPipe: a reusable pipeline segment with type-safe composition.
// ---------------------------------------------------------------------------
class TypedPipe[+In, -Out](private[rstream] val transforms: List[Transform[Any, Any]]) {
  def process(in: In): Out = {
    if (transforms.isEmpty) in.asInstanceOf[Out]
    else transforms.foldLeft(in.asInstanceOf[Any])((v, t) => t.apply(v)).asInstanceOf[Out]
  }

  def andThen[Next](next: TypedPipe[Out, Next]): TypedPipe[In, Next] =
    new TypedPipe[In, Next](next.transforms ++ transforms)
}

object TypedPipe {
  def fromTransform[A, B](t: Transform[A, B]): TypedPipe[A, B] =
    new TypedPipe[A, B](List(t.asInstanceOf[Transform[Any, Any]]))

  def identity[A]: TypedPipe[A, A] =
    new TypedPipe[A, A](Nil)
}
