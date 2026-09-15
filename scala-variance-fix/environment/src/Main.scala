package rstream


object Main {
  def main(args: Array[String]): Unit = {
    // T1: Emitter covariance — Emitter[Cat] assignable to Emitter[Animal]
    val catEmitter: Emitter[Cat] = SingleEmitter(Cat("Whiskers"))
    val animalEmitter: Emitter[Animal] = catEmitter
    println(s"T1:${animalEmitter.emit.name}")

    // T2: Receiver contravariance — Receiver[Animal] assignable to Receiver[Cat]
    val animalReceiver = new AccumulatingReceiver[Animal]
    val catReceiver: Receiver[Cat] = animalReceiver
    catReceiver.accept(Cat("Tom"))
    println(s"T2:${animalReceiver.snapshot.map(_.name).mkString(",")}")

    // T3: Transform variance — Transform[Animal,String] assignable to Transform[Cat,String]
    val animalTransform: Transform[Animal, String] = MapTransform((a: Animal) => a.name)
    val catTransform: Transform[Cat, String] = animalTransform
    println(s"T3:${catTransform.apply(Cat("Felix"))}")

    // T4: Emitter merge with different subtypes
    val cats: Emitter[Cat] = SeqEmitter(List(Cat("A"), Cat("B")))
    val dogs: Emitter[Dog] = SingleEmitter(Dog("Rex"))
    val merged: Emitter[Animal] = cats.merge(dogs)
    println(s"T4:${merged.take(3).map(_.name).mkString(",")}")

    // T5: BufferedEmitter caches and returns the same reference
    val buffered = new BufferedEmitter(SeqEmitter(List(Cat("C1"), Cat("C2"))))
    val first = buffered.emit
    val second = buffered.emit
    println(s"T5:${first.name},${second.name},${first eq second}")

    // T6: RecordingTransform records output history
    val recording = new RecordingTransform(MapTransform((c: Cat) => c.name.toUpperCase), 3)
    recording.apply(Cat("x"))
    recording.apply(Cat("y"))
    recording.apply(Cat("z"))
    println(s"T6:${recording.recent.mkString(",")}")

    // T7: Distributor sends to multiple receivers
    val r1 = new AccumulatingReceiver[Animal]
    val r2 = new AccumulatingReceiver[Animal]
    val dist = new Distributor(List(r1, r2))
    dist.send(Cat("Shared"))
    println(s"T7:${r1.snapshot.length},${r2.snapshot.length}")

    // T8: Pipeline connectN
    val pEmitter = SingleEmitter(Cat("Piped"))
    val pTransform = MapTransform((c: Cat) => s"name=${c.name}")
    val pReceiver = new AccumulatingReceiver[String]
    Pipeline.connectN(pEmitter, pTransform, pReceiver, 2)
    println(s"T8:${pReceiver.snapshot.mkString(";")}")

    // T9: Pipeline widenEmitter
    val widened: Emitter[Animal] = Pipeline.widenEmitter(catEmitter)
    println(s"T9:${widened.emit.name}")

    // T10: Encoder contramap — map input through function before encoding
    val nameEncoder: Encoder[String] = new Encoder[String] {
      def encode(a: String): String = s"[$a]"
    }
    val catNameEncoder: Encoder[Cat] = nameEncoder.contramap[Cat](_.name)
    println(s"T10:${catNameEncoder.encode(Cat("Luna"))}")

    // T11: Decoder map — transform output after decoding
    val rawDecoder: Decoder[String] = new Decoder[String] {
      def decode(s: String): String = s.trim
    }
    val catDecoder: Decoder[Cat] = rawDecoder.map(name => Cat(name))
    println(s"T11:${catDecoder.decode("  Nala  ").name}")

    // T12: CodecPair imap — invariant mapping round-trip
    val stringCodec = new CodecPair[String](
      new Encoder[String] { def encode(a: String): String = a.reverse },
      new Decoder[String] { def decode(s: String): String = s.reverse }
    )
    val intCodec: CodecPair[Int] = stringCodec.imap[Int](_.toInt, _.toString)
    val encoded = intCodec.encoder.encode(42)
    val decoded = intCodec.decoder.decode(encoded)
    println(s"T12:${encoded},${decoded}")

    // T13: Transform andThen composition
    val upper: Transform[String, String] = MapTransform(_.toUpperCase)
    val len: Transform[String, Int] = MapTransform(_.length)
    val composed: Transform[String, Int] = upper.andThen(len)
    println(s"T13:${composed.apply("hello")}")

    // T14: ReceiverOps contramap
    val stringReceiver = new AccumulatingReceiver[String]
    val intReceiver: Receiver[Int] =
      ReceiverOps.contramap[String, Int](stringReceiver, (i: Int) => i.toString)
    intReceiver.accept(42)
    intReceiver.accept(99)
    println(s"T14:${stringReceiver.snapshot.mkString(",")}")

    // T15: Pipeline composeTransforms
    val ct1: Transform[Cat, String] = MapTransform((c: Cat) => c.name)
    val ct2: Transform[String, Int] = MapTransform(_.length)
    val ct3: Transform[Cat, Int] = Pipeline.composeTransforms(ct1, ct2)
    println(s"T15:${ct3.apply(Cat("Mittens"))}")

    // T16: Encoder contravariance — direct subtype assignment
    val animalEnc: Encoder[Animal] = new Encoder[Animal] {
      def encode(a: Animal): String = a.name
    }
    val catEnc: Encoder[Cat] = animalEnc
    println(s"T16:${catEnc.encode(Cat("Ziggy"))}")

    // T17: Functor[Emitter].fmap must preserve all elements
    val seqCats = SeqEmitter(List(Cat("Mo"), Cat("Bo"), Cat("Jo")))
    val names: Emitter[String] = seqCats.fmap(_.name)
    println(s"T17:${names.take(3).mkString(",")}")

    // T18: ContravariantFunctor[Receiver].cmap must delegate correctly
    val accumStr = new AccumulatingReceiver[String]
    val intRcv: Receiver[Int] = accumStr.cmap((i: Int) => s"v$i")
    intRcv.accept(7)
    intRcv.accept(8)
    println(s"T18:${accumStr.snapshot.mkString(",")}")

    // T19: Profunctor[Transform].dimap must apply both f and g
    val double: Transform[Int, Int] = MapTransform((x: Int) => x * 2)
    val dimapped: Transform[String, Int] = double.dimap((s: String) => s.length, (i: Int) => i + 100)
    println(s"T19:${dimapped.apply("Cleo")}")

    // T20: NatTrans emitterToList converts correctly
    val singleCat = SingleEmitter(Cat("Milo"))
    val catList: List[Cat] = NatTrans.emitterToList.apply(singleCat)
    println(s"T20:${catList.map(_.name).mkString(",")}")

    // T21: Transform.compose (reverse of andThen)
    val toName: Transform[Cat, String] = MapTransform((c: Cat) => c.name)
    val toLen: Transform[String, Int] = MapTransform(_.length)
    val composedR: Transform[Cat, Int] = toLen.compose(toName)
    println(s"T21:${composedR.apply(Cat("Shadow"))}")

    // T22: Emitter.flatMap — monadic bind
    val catE = SingleEmitter(Cat("Dot"))
    val flatMapped: Emitter[String] = catE.flatMap(c => SeqEmitter(List(c.name, c.name.reverse)))
    println(s"T22:${flatMapped.take(2).mkString(",")}")

    // T23: TypedPipe composition with correct variance
    val pipe1 = TypedPipe.fromTransform(MapTransform((c: Cat) => c.name))
    val pipe2 = TypedPipe.fromTransform(MapTransform((s: String) => s.length))
    val combined = pipe1.andThen(pipe2)
    val animalNamePipe: TypedPipe[Animal, String] = TypedPipe.fromTransform(MapTransform((a: Animal) => a.name))
    val catAnyPipe: TypedPipe[Cat, Any] = animalNamePipe
    println(s"T23:${combined.process(Cat("Bella"))},${catAnyPipe.process(Cat("Zara"))}")

    // T24: ReceiverOps.fanOut distributes to multiple receivers
    val fo1 = new AccumulatingReceiver[String]
    val fo2 = new AccumulatingReceiver[String]
    val fo3 = new AccumulatingReceiver[String]
    val fanned: Receiver[String] = ReceiverOps.fanOut(fo1, fo2, fo3)
    fanned.accept("hello")
    println(s"T24:${fo1.snapshot.length},${fo2.snapshot.length},${fo3.snapshot.length}")

    // T25: TypeWitness reflexive conversion
    val reflW = summon[TypeWitness[Cat, Cat]]
    println(s"T25:${reflW.convert(Cat("Cleo")).name}")

    // T26: TypeWitness Cat→Animal via given evidence
    val catAnimalW = summon[TypeWitness[Cat, Animal]]
    val asAnimal: Animal = catAnimalW.convert(Cat("Oscar"))
    println(s"T26:${asAnimal.name}")

    // T27: TypeSafeChannel send with evidence, FIFO order
    val ch = TypeSafeChannel.empty[Animal]
      .send(Cat("Ivy"))
      .send(Dog("Max"))
    println(s"T27:${ch.receiveAll.map(_.name).mkString(",")}")

    // T28: Monad[Emitter] bind preserves all elements
    val mCats = SeqEmitter(List(Cat("Poe"), Cat("Ray")))
    val mBound: Emitter[String] = mCats.bind(c => SingleEmitter(c.name))
    println(s"T28:${mBound.take(2).mkString(",")}")

    // T29: TypeSafeChannel.of + transform + merge
    val chA = TypeSafeChannel.of("hello", "world")
    val chB = TypeSafeChannel.of("!")
    val chMerged = chA.merge(chB)
    val chUpper = chMerged.transform(_.toUpperCase)
    println(s"T29:${chUpper.receiveAll.mkString(",")}")

    // T30: Monad pure + bind left identity
    val mE = summon[Monad[Emitter]]
    val leftId: Emitter[String] = mE.pure(Cat("Luna")).bind(c => SeqEmitter(List(c.name, c.name.reverse)))
    println(s"T30:${leftId.take(2).mkString(",")}")

    println("ALL_CHECKS_PASSED")
  }
}
