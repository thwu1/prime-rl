package rstream


// ---------------------------------------------------------------------------
// Encoder: serializes values of type A to String
// ---------------------------------------------------------------------------
trait Encoder[+A] {
  def encode(a: A): String
  def contramap[B](f: B => A): Encoder[B] = ???
}

// ---------------------------------------------------------------------------
// Decoder: deserializes String to values of type A
// ---------------------------------------------------------------------------
trait Decoder[-A] {
  def decode(s: String): A
  def map[B](f: A => B): Decoder[B] = ???
}

// ---------------------------------------------------------------------------
// CodecPair: combines an Encoder and Decoder for the same type.
// Invariant in A because it both reads and writes.
// ---------------------------------------------------------------------------
class CodecPair[A](val encoder: Encoder[A], val decoder: Decoder[A]) {
  def imap[B](f: A => B, g: B => A): CodecPair[B] = ???
}
