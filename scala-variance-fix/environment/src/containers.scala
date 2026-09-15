package rstream


// ---------------------------------------------------------------------------
// BufferedEmitter: wraps an Emitter and caches the last emitted value.
// ---------------------------------------------------------------------------
class BufferedEmitter[+A](underlying: Emitter[A]) {
  private var buffer: Option[A] = None

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

// ---------------------------------------------------------------------------
// RecordingTransform: wraps a Transform and records the most recent outputs.
// ---------------------------------------------------------------------------
class RecordingTransform[-A, +B](transform: Transform[A, B], capacity: Int) {
  private var history: List[B] = Nil

  def apply(a: A): B = {
    val result = transform.apply(a)
    history = (result :: history).take(capacity)
    result
  }

  def recent: List[B] = history.reverse
}

// ---------------------------------------------------------------------------
// ReceiverOps: utilities for composing Receivers.
// ---------------------------------------------------------------------------
object ReceiverOps {
  def contramap[A, B](receiver: Receiver[A], f: B => A): Receiver[B] = ???

  def fanOut[A](receivers: Receiver[A]*): Receiver[A] = ???
}
