package rstream


// ---------------------------------------------------------------------------
// TypeWitness: evidence that a value of type From can be converted to type To
// ---------------------------------------------------------------------------
sealed trait TypeWitness[+From, -To] {
  def convert(a: From): To
}

case class ReflWitness[A]() extends TypeWitness[A, A] {
  def convert(a: A): A = a
}

case class TransWitness[A, B, C](first: TypeWitness[A, B], second: TypeWitness[B, C])
    extends TypeWitness[A, C] {
  def convert(a: A): C = second.convert(first.convert(a))
}

// ---------------------------------------------------------------------------
// TypeSafeChannel: type-safe message channel using evidence-based send
// ---------------------------------------------------------------------------
class TypeSafeChannel[A] private (private val messages: List[Any]) {
  def send[B](msg: B)(using ev: TypeWitness[B, A]): TypeSafeChannel[A] =
    new TypeSafeChannel[A](ev.convert(msg) :: messages)

  def receive: Option[(A, TypeSafeChannel[A])] = messages match {
    case Nil => None
    case head :: tail => Some((head.asInstanceOf[A], new TypeSafeChannel[A](tail)))
  }

  def receiveAll: List[A] = messages.map(_.asInstanceOf[A])

  def transform[B](f: A => B): TypeSafeChannel[B] =
    new TypeSafeChannel[B](messages.map(m => f(m.asInstanceOf[A])))

  def merge(other: TypeSafeChannel[A]): TypeSafeChannel[A] =
    new TypeSafeChannel[A](messages ++ other.messages)

  def size: Int = messages.length
}

object TypeSafeChannel {
  def empty[A]: TypeSafeChannel[A] = new TypeSafeChannel[A](Nil)

  def of[A](values: A*): TypeSafeChannel[A] =
    new TypeSafeChannel[A](values.toList.reverse)
}

// ---------------------------------------------------------------------------
// Given evidence instances for the Animal hierarchy
// ---------------------------------------------------------------------------
given [A]: TypeWitness[A, A] = ReflWitness[A]()

given TypeWitness[Cat, Animal] with {
  def convert(a: Cat): Animal = ???
}

given TypeWitness[Dog, Animal] with {
  def convert(a: Dog): Animal = ???
}
