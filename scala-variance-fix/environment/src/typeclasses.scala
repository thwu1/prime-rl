package rstream


// ---------------------------------------------------------------------------
// Higher-kinded type classes for variance-aware generic programming
// ---------------------------------------------------------------------------

trait Functor[F[_]] {
  extension [A](fa: F[A]) def fmap[B](f: A => B): F[B]
}

trait ContravariantFunctor[F[_]] {
  extension [A](fa: F[A]) def cmap[B](f: B => A): F[B]
}

trait Profunctor[P[_, _]] {
  extension [A, B](pab: P[A, B]) def dimap[C, D](f: C => A, g: B => D): P[C, D]
}

// ---------------------------------------------------------------------------
// Monad: monadic bind for covariant type constructors
// ---------------------------------------------------------------------------
trait Monad[F[_]] {
  def pure[A](a: A): F[A]
  extension [A](fa: F[A]) def bind[B](f: A => F[B]): F[B]
}

// ---------------------------------------------------------------------------
// Type class instances
// ---------------------------------------------------------------------------

given Functor[Emitter] with {
  extension [A](fa: Emitter[A]) def fmap[B](f: A => B): Emitter[B] =
    SingleEmitter(f(fa.emit))
}

given ContravariantFunctor[Receiver] with {
  extension [A](fa: Receiver[A]) def cmap[B](f: B => A): Receiver[B] =
    new Receiver[B] { def accept(b: B): Unit = () }
}

given ContravariantFunctor[Encoder] with {
  extension [A](fa: Encoder[A]) def cmap[B](f: B => A): Encoder[B] = fa.contramap(f)
}

given Functor[Decoder] with {
  extension [A](fa: Decoder[A]) def fmap[B](f: A => B): Decoder[B] = fa.map(f)
}

given Profunctor[Transform] with {
  extension [A, B](pab: Transform[A, B]) def dimap[C, D](f: C => A, g: B => D): Transform[C, D] =
    MapTransform(c => pab.apply(f(c)).asInstanceOf[D])
}

given Monad[Emitter] with {
  def pure[A](a: A): Emitter[A] = SingleEmitter(a)
  extension [A](fa: Emitter[A]) def bind[B](f: A => Emitter[B]): Emitter[B] =
    SingleEmitter(f(fa.emit).emit)
}

// ---------------------------------------------------------------------------
// Natural transformation between type constructors
// ---------------------------------------------------------------------------
trait NatTrans[F[_], G[_]] {
  def apply[A](fa: F[A]): G[A]
}

object NatTrans {
  def emitterToList: NatTrans[Emitter, List] = new NatTrans[Emitter, List] {
    def apply[A](fa: Emitter[A]): List[A] = Nil
  }
}
