#!/usr/bin/env python3
"""
Fix all variance annotations, type bounds, access modifiers, implement
all ??? placeholders, correct runtime logic errors, fix type evidence
and channel ordering, and fix monad bind in the rstream library.

"""

import os
import sys

SRC_DIR = '/app/src'
os.makedirs(SRC_DIR, exist_ok=True)

# ---- Corrected file contents ----

CORRECTED_CORE = '''\
package rstream


trait Animal { def name: String }
case class Cat(name: String) extends Animal
case class Dog(name: String) extends Animal

sealed trait Emitter[+A] {
  def emit: A
  def map[B](f: A => B): Emitter[B]
  def take(n: Int): List[A]
  def merge[B >: A](other: Emitter[B]): Emitter[B]
  def flatMap[B](f: A => Emitter[B]): Emitter[B]
}

final case class SingleEmitter[A](value: A) extends Emitter[A] {
  def emit: A = value
  def map[B](f: A => B): Emitter[B] = SingleEmitter(f(value))
  def take(n: Int): List[A] = List.fill(n)(value)
  def merge[B >: A](other: Emitter[B]): Emitter[B] =
    SeqEmitter(List(value, other.emit))
  def flatMap[B](f: A => Emitter[B]): Emitter[B] = f(value)
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
  def merge[B >: A](other: Emitter[B]): Emitter[B] =
    SeqEmitter(values ++ List(other.emit))
  def flatMap[B](f: A => Emitter[B]): Emitter[B] =
    SeqEmitter(values.flatMap(a => f(a).take(1)))
}

trait Receiver[-A] {
  def accept(a: A): Unit
}

class AccumulatingReceiver[A] extends Receiver[A] {
  private val buf = scala.collection.mutable.ListBuffer.empty[A]
  def accept(a: A): Unit = { buf += a }
  def snapshot: List[A] = buf.toList
}

trait Transform[-A, +B] { self =>
  def apply(a: A): B
  def andThen[C](next: Transform[B, C]): Transform[A, C] =
    MapTransform(a => next.apply(self.apply(a)))
  def compose[Z](prev: Transform[Z, A]): Transform[Z, B] =
    MapTransform(z => self.apply(prev.apply(z)))
}

final case class MapTransform[A, B](f: A => B) extends Transform[A, B] {
  def apply(a: A): B = f(a)
}
'''

CORRECTED_CODEC = '''\
package rstream


trait Encoder[-A] {
  def encode(a: A): String
  def contramap[B](f: B => A): Encoder[B] = {
    val self = this
    new Encoder[B] {
      def encode(b: B): String = self.encode(f(b))
    }
  }
}

trait Decoder[+A] {
  def decode(s: String): A
  def map[B](f: A => B): Decoder[B] = {
    val self = this
    new Decoder[B] {
      def decode(s: String): B = f(self.decode(s))
    }
  }
}

class CodecPair[A](val encoder: Encoder[A], val decoder: Decoder[A]) {
  def imap[B](f: A => B, g: B => A): CodecPair[B] =
    new CodecPair[B](encoder.contramap(g), decoder.map(f))
}
'''

CORRECTED_TYPECLASSES = '''\
package rstream


trait Functor[F[_]] {
  extension [A](fa: F[A]) def fmap[B](f: A => B): F[B]
}

trait ContravariantFunctor[F[_]] {
  extension [A](fa: F[A]) def cmap[B](f: B => A): F[B]
}

trait Profunctor[P[_, _]] {
  extension [A, B](pab: P[A, B]) def dimap[C, D](f: C => A, g: B => D): P[C, D]
}

trait Monad[F[_]] {
  def pure[A](a: A): F[A]
  extension [A](fa: F[A]) def bind[B](f: A => F[B]): F[B]
}

given Functor[Emitter] with {
  extension [A](fa: Emitter[A]) def fmap[B](f: A => B): Emitter[B] = fa.map(f)
}

given ContravariantFunctor[Receiver] with {
  extension [A](fa: Receiver[A]) def cmap[B](f: B => A): Receiver[B] =
    new Receiver[B] { def accept(b: B): Unit = fa.accept(f(b)) }
}

given ContravariantFunctor[Encoder] with {
  extension [A](fa: Encoder[A]) def cmap[B](f: B => A): Encoder[B] = fa.contramap(f)
}

given Functor[Decoder] with {
  extension [A](fa: Decoder[A]) def fmap[B](f: A => B): Decoder[B] = fa.map(f)
}

given Profunctor[Transform] with {
  extension [A, B](pab: Transform[A, B]) def dimap[C, D](f: C => A, g: B => D): Transform[C, D] =
    MapTransform(c => g(pab.apply(f(c))))
}

given Monad[Emitter] with {
  def pure[A](a: A): Emitter[A] = SingleEmitter(a)
  extension [A](fa: Emitter[A]) def bind[B](f: A => Emitter[B]): Emitter[B] =
    fa.flatMap(f)
}

trait NatTrans[F[_], G[_]] {
  def apply[A](fa: F[A]): G[A]
}

object NatTrans {
  def emitterToList: NatTrans[Emitter, List] = new NatTrans[Emitter, List] {
    def apply[A](fa: Emitter[A]): List[A] = fa.take(1)
  }
}
'''

CORRECTED_EVIDENCE = '''\
package rstream


sealed trait TypeWitness[From, To] {
  def convert(a: From): To
}

case class ReflWitness[A]() extends TypeWitness[A, A] {
  def convert(a: A): A = a
}

case class TransWitness[A, B, C](first: TypeWitness[A, B], second: TypeWitness[B, C])
    extends TypeWitness[A, C] {
  def convert(a: A): C = second.convert(first.convert(a))
}

class TypeSafeChannel[A] private (private val messages: List[Any]) {
  def send[B](msg: B)(using ev: TypeWitness[B, A]): TypeSafeChannel[A] =
    new TypeSafeChannel[A](messages :+ ev.convert(msg))

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
    new TypeSafeChannel[A](values.toList)
}

given [A]: TypeWitness[A, A] = ReflWitness[A]()

given TypeWitness[Cat, Animal] with {
  def convert(a: Cat): Animal = a
}

given TypeWitness[Dog, Animal] with {
  def convert(a: Dog): Animal = a
}
'''

CORRECTED_CONTAINERS = '''\
package rstream


class BufferedEmitter[+A](underlying: Emitter[A]) {
  private[this] var buffer: Option[A] = None

  def emit: A = buffer match {
    case Some(v) => v
    case None =>
      val v = underlying.emit
      buffer = Some(v)
      v
  }

  def refresh(): A = {
    val v = underlying.emit
    buffer = Some(v)
    v
  }

  def peek: Option[A] = buffer
}

class RecordingTransform[-A, +B](transform: Transform[A, B], capacity: Int) {
  private[this] var history: List[B] = Nil

  def apply(a: A): B = {
    val result = transform.apply(a)
    history = (result :: history).take(capacity)
    result
  }

  def recent: List[B] = history.reverse
}

object ReceiverOps {
  def contramap[A, B](receiver: Receiver[A], f: B => A): Receiver[B] =
    new Receiver[B] {
      def accept(b: B): Unit = receiver.accept(f(b))
    }

  def fanOut[A](receivers: Receiver[A]*): Receiver[A] =
    new Receiver[A] {
      def accept(a: A): Unit = receivers.foreach(_.accept(a))
    }
}
'''

CORRECTED_PIPELINE = '''\
package rstream


object Pipeline {
  def connect[A, B](emitter: Emitter[A], transform: Transform[A, B],
                    receiver: Receiver[B]): Unit =
    receiver.accept(transform.apply(emitter.emit))

  def connectN[A, B](emitter: Emitter[A], transform: Transform[A, B],
                     receiver: Receiver[B], n: Int): Unit =
    (0 until n).foreach(_ => receiver.accept(transform.apply(emitter.emit)))

  def widenEmitter[A, B >: A](emitter: Emitter[A]): Emitter[B] = emitter

  def composeTransforms[A, B, C](t1: Transform[A, B],
                                  t2: Transform[B, C]): Transform[A, C] =
    MapTransform(a => t2.apply(t1.apply(a)))
}

class Distributor[-A](receivers: List[Receiver[A]]) {
  def send(a: A): Unit = receivers.foreach(_.accept(a))
}

class TypedPipe[-In, +Out](private[rstream] val transforms: List[Transform[Any, Any]]) {
  def process(in: In): Out = {
    if (transforms.isEmpty) in.asInstanceOf[Out]
    else transforms.foldLeft(in.asInstanceOf[Any])((v, t) => t.apply(v)).asInstanceOf[Out]
  }

  def andThen[Next](next: TypedPipe[Out, Next]): TypedPipe[In, Next] =
    new TypedPipe[In, Next](transforms ++ next.transforms)
}

object TypedPipe {
  def fromTransform[A, B](t: Transform[A, B]): TypedPipe[A, B] =
    new TypedPipe[A, B](List(t.asInstanceOf[Transform[Any, Any]]))

  def identity[A]: TypedPipe[A, A] =
    new TypedPipe[A, A](Nil)
}
'''


def write_file(path, content):
    """Write content to a file."""
    with open(path, 'w') as f:
        f.write(content)
    print(f"  wrote {path}")


def apply_fixes():
    """Write all corrected source files."""
    write_file(os.path.join(SRC_DIR, 'core.scala'), CORRECTED_CORE)
    write_file(os.path.join(SRC_DIR, 'codec.scala'), CORRECTED_CODEC)
    write_file(os.path.join(SRC_DIR, 'typeclasses.scala'), CORRECTED_TYPECLASSES)
    write_file(os.path.join(SRC_DIR, 'evidence.scala'), CORRECTED_EVIDENCE)
    write_file(os.path.join(SRC_DIR, 'containers.scala'), CORRECTED_CONTAINERS)
    write_file(os.path.join(SRC_DIR, 'pipeline.scala'), CORRECTED_PIPELINE)
    print("\nAll fixes applied successfully.")


if __name__ == '__main__':
    apply_fixes()
