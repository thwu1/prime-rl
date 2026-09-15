A Scala 3 library at `/app/src/` implements a typed data-flow processing framework. The library defines generic types for emitting, receiving, and transforming data, serialization codecs, higher-kinded type class abstractions (Functor, ContravariantFunctor, Profunctor, Monad), natural transformations, type evidence witnesses, type-safe channels, and composable pipeline segments. The code fails to compile due to systematic variance annotation errors, incorrect type bounds, and access modifier violations. Several methods are unimplemented (`???`). Beyond compilation errors, some type class instances, evidence instances, channel operations, and pipeline compositions contain logic errors that produce incorrect results at runtime.

Source files in `/app/src/`:

- `core.scala` — `Emitter[A]`, `Receiver[A]`, `Transform[A, B]` with concrete implementations
- `codec.scala` — `Encoder[A]`, `Decoder[A]`, `CodecPair[A]` with mapping methods
- `typeclasses.scala` — `Functor[F[_]]`, `ContravariantFunctor[F[_]]`, `Profunctor[P[_,_]]`, `Monad[F[_]]` with `given` instances and `NatTrans` natural transformations
- `evidence.scala` — `TypeWitness[From, To]`, `ReflWitness`, `TransWitness`, `TypeSafeChannel[A]` with given evidence instances
- `containers.scala` — `BufferedEmitter[A]`, `RecordingTransform[A, B]`, `ReceiverOps` utilities
- `pipeline.scala` — `Pipeline` wiring utilities, `Distributor[A]`, `TypedPipe[In, Out]` composable pipeline segments
- `Main.scala` — runtime validation performing 30 checks (do not modify)
- `project.scala` — Scala version directive (do not modify)

Fix all compilation errors, implement all `???` placeholders, and correct all runtime logic errors so that:

1. `scala-cli compile /app/src/` succeeds (exit code 0)
2. `scala-cli run /app/src/` produces output ending with `ALL_CHECKS_PASSED`

The `Main` object exercises the complete type hierarchy using `Cat <: Animal` / `Dog <: Animal` test data: subtype assignment through covariant/contravariant types, cross-subtype merging with type widening, monadic bind on emitters, mutable caching within variance-annotated wrappers, transform composition (forward and reverse), codec mapping, type class operations via `given` extension methods (functor map, contravariant map, profunctor dimap, monad bind/pure), natural transformations between type constructors, type evidence conversion with `given`/`using` implicit resolution, type-safe channel FIFO ordering with evidence-gated send, channel transform/merge operations, typed pipeline segment composition with variance-correct subtype assignment, and receiver fan-out distribution. Each check prints a tagged output line (T1–T30); all must match expected values.

Errors span multiple files and categories; some become visible only after others are resolved. Type class instances depend on correct variance in underlying types. Evidence instances require compilable type witness definitions. Channel ordering bugs surface only after evidence compilation succeeds. Runtime logic errors in type class instances and pipeline compositions are only discoverable after all compilation errors are resolved.

JDK 17 is pre-installed. Install Scala 3 tooling (e.g., `scala-cli`) as needed.
