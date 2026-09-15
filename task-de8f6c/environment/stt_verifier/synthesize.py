"""TTS audio generation using espeak-ng."""
import os
import subprocess
import tempfile


def synthesize_speech(text, output_path, rate=175):
    """Generate WAV audio from text using espeak-ng.

    Parameters
    ----------
    text : str
        Text to synthesize.
    output_path : str
        Path for the output WAV file.
    rate : int
        Speech rate in words per minute.
    """
    subprocess.run(
        ['espeak-ng', '-w', output_path, '-s', str(rate), text],
        check=True,
        capture_output=True,
    )


def create_interrupted_audio(utterances, output_path, silence_gap_ms=500):
    """Generate multi-utterance audio with optional interruption.

    Parameters
    ----------
    utterances : list[dict]
        Each dict has 'text', optional 'interrupt_after_ms', optional 'speech_rate'.
    output_path : str
        Path for the combined output WAV file.
    silence_gap_ms : int
        Silence duration between utterances in milliseconds.
    """
    import numpy as np
    import soundfile as sf

    segments = []
    sr = None

    for utt in utterances:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            tmp_path = f.name

        try:
            rate = utt.get('speech_rate', 175)
            synthesize_speech(utt['text'], tmp_path, rate=rate)
            audio, file_sr = sf.read(tmp_path)

            if sr is None:
                sr = file_sr

            # Truncate if interrupted
            if 'interrupt_after_ms' in utt:
                max_samples = int(sr * utt['interrupt_after_ms'] / 1000)
                audio = audio[:max_samples]

            segments.append(audio)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    if sr is None:
        sr = 16000

    # Concatenate with silence gaps
    silence = np.zeros(int(sr * silence_gap_ms / 1000))
    parts = []
    for i, seg in enumerate(segments):
        if i > 0:
            parts.append(silence)
        parts.append(seg)

    if parts:
        combined = np.concatenate(parts)
    else:
        combined = np.zeros(1)

    sf.write(output_path, combined, int(sr))
