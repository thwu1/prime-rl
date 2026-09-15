package rstream


trait Animal { def name: String }
case class Cat(name: String) extends Animal
case class Dog(name: String) extends Animal

// ---------------------------------------------------------------------------
// Emitter: produces values of type A
// ---------------------------------------------------------------------------
sealed trait Emitter[-A] {
  def emit: A
  def map[B](f: A => B): Emitter[B]
  def take(n: Int): List[A]
  def merge(other: Emitter[A]): Emitter[A]
  def flatMap[B](f: A => Emitter[B]): Emitter[B]
}

final case class SingleEmitter[A](value: A) extends Emitter[A] {
  def emit: A = value
  def map[B](f: A => B): Emitter[B] = SingleEmitter(f(value))
  def take(n: Int): List[A] = List.fill(n)(value)
  def merge(other: Emitter[A]): Emitter[A] =
    SeqEmitter(List(value, other.emit))
  def flatMap[B](f: A => Emitter[B]): Emitter[B] = ???
}

final case class SeqEmitter[A](values: List[A]) extends Emitter[A] {
  require(values.nonEmpty, "SeqEmitter requires at least one value")
  private var idx = 0
  def emit: A = {
    val v = values(idx % values.length)
    idx += 1
    v
  }
  def map[B](f: A => B): Emitter[B] = SeqEmitter(values.map(f))
  def take(n: Int): List[A] = (0 until n).toList.map(_ => emit)
  def merge(other: Emitter[A]): Emitter[A] =
    SeqEmitter(values ++ List(other.emit))
  def flatMap[B](f: A => Emitter[B]): Emitter[B] = ???
}

// ---------------------------------------------------------------------------
// Receiver: consumes values of type A
// ---------------------------------------------------------------------------
trait Receiver[+A] {
  def accept(a: A): Unit
}

class AccumulatingReceiver[A] extends Receiver[A] {
  private val buf = scala.collection.mutable.ListBuffer.empty[A]
  def accept(a: A): Unit = { buf += a }
  def snapshot: List[A] = buf.toList
}

// ---------------------------------------------------------------------------
// Transform: converts values from type A to type B
// ---------------------------------------------------------------------------
trait Transform[+A, -B] { self =>
  def apply(a: A): B
  def andThen[C](next: Transform[B, C]): Transform[A, C] = ???
  def compose[Z](prev: Transform[Z, A]): Transform[Z, B] = ???
}

final case class MapTransform[A, B](f: A => B) extends Transform[A, B] {
  def apply(a: A): B = f(a)
}
