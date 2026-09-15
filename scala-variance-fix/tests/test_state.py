"""
Tests for the variance-codec-pipeline task.

Verifies that:
  1. All Scala source files in /app/src/ compile without errors.
  2. The compiled program runs and produces correct output demonstrating
     that variance annotations, type bounds, access modifiers, method
     implementations, type class instances, type evidence, channel
     ordering, monad operations, and pipeline compositions are all correct.
"""


import subprocess
import pytest


COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 180


@pytest.fixture(scope="session")
def compilation():
    """Compile all Scala source files."""
    result = subprocess.run(
        ["scala-cli", "compile", "/app/src/"],
        capture_output=True, text=True, timeout=COMPILE_TIMEOUT
    )
    return result


@pytest.fixture(scope="session")
def execution(compilation):
    """Compile and run the Scala program (depends on compilation)."""
    result = subprocess.run(
        ["scala-cli", "run", "/app/src/"],
        capture_output=True, text=True, timeout=RUN_TIMEOUT
    )
    return result


def test_compiles_without_errors(compilation):
    """The code must compile without errors."""
    assert compilation.returncode == 0, (
        f"Compilation failed with exit code {compilation.returncode}.\n"
        f"stderr:\n{compilation.stderr}\n"
        f"stdout:\n{compilation.stdout}"
    )


def test_runs_successfully(execution):
    """The compiled program must execute without runtime errors."""
    assert execution.returncode == 0, (
        f"Runtime failed with exit code {execution.returncode}.\n"
        f"stderr:\n{execution.stderr}\n"
        f"stdout:\n{execution.stdout}"
    )


def test_t1_emitter_covariance(execution):
    """Emitter[Cat] must be assignable to Emitter[Animal] (covariance)."""
    assert "T1:Whiskers" in execution.stdout, (
        f"Emitter covariance test failed.\nOutput:\n{execution.stdout}"
    )


def test_t2_receiver_contravariance(execution):
    """Receiver[Animal] must be assignable to Receiver[Cat] (contravariance)."""
    assert "T2:Tom" in execution.stdout, (
        f"Receiver contravariance test failed.\nOutput:\n{execution.stdout}"
    )


def test_t3_transform_variance(execution):
    """Transform[Animal,String] must be assignable to Transform[Cat,String]."""
    assert "T3:Felix" in execution.stdout, (
        f"Transform variance test failed.\nOutput:\n{execution.stdout}"
    )


def test_t4_emitter_merge_widening(execution):
    """Emitter[Cat].merge(Emitter[Dog]) must produce Emitter[Animal]."""
    assert "T4:A,B,Rex" in execution.stdout, (
        f"Emitter merge test failed.\nOutput:\n{execution.stdout}"
    )


def test_t5_buffered_emitter(execution):
    """BufferedEmitter must cache and return the same reference."""
    assert "T5:C1,C1,true" in execution.stdout, (
        f"BufferedEmitter test failed.\nOutput:\n{execution.stdout}"
    )


def test_t6_recording_transform(execution):
    """RecordingTransform must record output history in order."""
    assert "T6:X,Y,Z" in execution.stdout, (
        f"RecordingTransform test failed.\nOutput:\n{execution.stdout}"
    )


def test_t7_distributor(execution):
    """Distributor must send values to all receivers."""
    assert "T7:1,1" in execution.stdout, (
        f"Distributor test failed.\nOutput:\n{execution.stdout}"
    )


def test_t8_pipeline_connect(execution):
    """Pipeline.connectN must pipe emitter through transform to receiver."""
    assert "T8:name=Piped;name=Piped" in execution.stdout, (
        f"Pipeline connectN test failed.\nOutput:\n{execution.stdout}"
    )


def test_t9_widen_emitter(execution):
    """Pipeline.widenEmitter must correctly widen Emitter types."""
    assert "T9:Whiskers" in execution.stdout, (
        f"widenEmitter test failed.\nOutput:\n{execution.stdout}"
    )


def test_t10_encoder_contramap(execution):
    """Encoder.contramap must correctly pre-process input before encoding."""
    assert "T10:[Luna]" in execution.stdout, (
        f"Encoder contramap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t11_decoder_map(execution):
    """Decoder.map must correctly post-process output after decoding."""
    assert "T11:Nala" in execution.stdout, (
        f"Decoder map test failed.\nOutput:\n{execution.stdout}"
    )


def test_t12_codec_imap(execution):
    """CodecPair.imap must round-trip correctly through invariant mapping."""
    assert "T12:24,42" in execution.stdout, (
        f"CodecPair imap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t13_transform_andthen(execution):
    """Transform.andThen must compose transforms correctly."""
    assert "T13:5" in execution.stdout, (
        f"Transform andThen test failed.\nOutput:\n{execution.stdout}"
    )


def test_t14_receiver_contramap(execution):
    """ReceiverOps.contramap must create a contramapped receiver."""
    assert "T14:42,99" in execution.stdout, (
        f"ReceiverOps contramap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t15_compose_transforms(execution):
    """Pipeline.composeTransforms must chain two transforms."""
    assert "T15:7" in execution.stdout, (
        f"Pipeline composeTransforms test failed.\nOutput:\n{execution.stdout}"
    )


def test_t16_encoder_contravariance_assignment(execution):
    """Encoder[Animal] must be directly assignable to Encoder[Cat]."""
    assert "T16:Ziggy" in execution.stdout, (
        f"Encoder contravariance assignment test failed.\nOutput:\n{execution.stdout}"
    )


def test_t17_functor_emitter_fmap(execution):
    """Functor[Emitter].fmap must preserve all elements via map."""
    assert "T17:Mo,Bo,Jo" in execution.stdout, (
        f"Functor fmap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t18_contravariant_receiver_cmap(execution):
    """ContravariantFunctor[Receiver].cmap must delegate to underlying receiver."""
    assert "T18:v7,v8" in execution.stdout, (
        f"ContravariantFunctor cmap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t19_profunctor_dimap(execution):
    """Profunctor[Transform].dimap must apply both pre and post functions."""
    assert "T19:108" in execution.stdout, (
        f"Profunctor dimap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t20_nattrans_emitter_to_list(execution):
    """NatTrans.emitterToList must convert emitter to non-empty list."""
    assert "T20:Milo" in execution.stdout, (
        f"NatTrans emitterToList test failed.\nOutput:\n{execution.stdout}"
    )


def test_t21_transform_compose(execution):
    """Transform.compose must compose in reverse order (apply prev then self)."""
    assert "T21:6" in execution.stdout, (
        f"Transform compose test failed.\nOutput:\n{execution.stdout}"
    )


def test_t22_emitter_flatmap(execution):
    """Emitter.flatMap must implement monadic bind correctly."""
    assert "T22:Dot,toD" in execution.stdout, (
        f"Emitter flatMap test failed.\nOutput:\n{execution.stdout}"
    )


def test_t23_typedpipe_composition(execution):
    """TypedPipe must compose correctly and support variance-based assignment."""
    assert "T23:5,Zara" in execution.stdout, (
        f"TypedPipe composition test failed.\nOutput:\n{execution.stdout}"
    )


def test_t24_receiver_fanout(execution):
    """ReceiverOps.fanOut must distribute values to all receivers."""
    assert "T24:1,1,1" in execution.stdout, (
        f"ReceiverOps fanOut test failed.\nOutput:\n{execution.stdout}"
    )


def test_t25_typewitness_reflexive(execution):
    """TypeWitness reflexive conversion must round-trip identity."""
    assert "T25:Cleo" in execution.stdout, (
        f"TypeWitness reflexive test failed.\nOutput:\n{execution.stdout}"
    )


def test_t26_typewitness_subtype(execution):
    """TypeWitness Cat→Animal must convert via given evidence."""
    assert "T26:Oscar" in execution.stdout, (
        f"TypeWitness subtype evidence test failed.\nOutput:\n{execution.stdout}"
    )


def test_t27_channel_send_fifo(execution):
    """TypeSafeChannel send must maintain FIFO ordering."""
    assert "T27:Ivy,Max" in execution.stdout, (
        f"TypeSafeChannel FIFO test failed.\nOutput:\n{execution.stdout}"
    )


def test_t28_monad_bind(execution):
    """Monad[Emitter].bind must preserve all elements."""
    assert "T28:Poe,Ray" in execution.stdout, (
        f"Monad bind test failed.\nOutput:\n{execution.stdout}"
    )


def test_t29_channel_of_transform_merge(execution):
    """TypeSafeChannel.of + transform + merge must maintain order."""
    assert "T29:HELLO,WORLD,!" in execution.stdout, (
        f"TypeSafeChannel of/transform/merge test failed.\nOutput:\n{execution.stdout}"
    )


def test_t30_monad_left_identity(execution):
    """Monad pure + bind must satisfy left identity law."""
    assert "T30:Luna,anuL" in execution.stdout, (
        f"Monad left identity test failed.\nOutput:\n{execution.stdout}"
    )


def test_all_checks_passed(execution):
    """The program must print ALL_CHECKS_PASSED."""
    assert "ALL_CHECKS_PASSED" in execution.stdout, (
        f"Final check failed — ALL_CHECKS_PASSED not in output.\n"
        f"Output:\n{execution.stdout}"
    )
