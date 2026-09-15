"""Energy-based Voice Activity Detection for audio segmentation."""
import numpy as np
import soundfile as sf


def segment_utterances(audio_path, min_silence_ms=500, energy_threshold_db=-40.0):
    """Segment a WAV file into utterances based on frame energy.

    Parameters
    ----------
    audio_path : str
        Path to the WAV file.
    min_silence_ms : int
        Minimum silence gap (ms) to split segments.
    energy_threshold_db : float
        RMS energy threshold in dB; frames above this are speech.

    Returns
    -------
    list[dict]
        Each dict has 'start' and 'end' timestamps in seconds.
    """
    audio, sr = sf.read(audio_path)

    # Convert to mono
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    frame_length = int(sr * 0.010)  # 10 ms
    hop_length = int(sr * 0.025)    # 25 ms

    num_frames = max(0, (len(audio) - frame_length) // hop_length + 1)
    if num_frames == 0:
        return []

    # Compute per-frame RMS energy in dB
    energy_db = np.full(num_frames, -100.0)
    for i in range(num_frames):
        start = i * hop_length
        frame = audio[start:start + frame_length]
        rms = np.sqrt(np.mean(frame ** 2))
        energy_db[i] = 20.0 * np.log10(rms + 1e-10)

    is_speech = energy_db > energy_threshold_db

    # Walk through frames and collect segments
    min_silence_frames = int(min_silence_ms / 10)   # 10 ms per frame
    min_speech_frames = int(100 / 10)                # 100 ms minimum speech

    segments = []
    in_speech = False
    speech_start = 0
    silence_count = 0

    for i in range(len(is_speech)):
        if is_speech[i]:
            if not in_speech:
                speech_start = i
                in_speech = True
            silence_count = 0
        else:
            if in_speech:
                silence_count += 1
                if silence_count >= min_silence_frames:
                    speech_end = i - silence_count
                    if speech_end - speech_start >= min_speech_frames:
                        segments.append({
                            'start': round(speech_start * 0.010, 4),
                            'end': round(speech_end * 0.010, 4),
                        })
                    in_speech = False
                    silence_count = 0

    # Flush trailing speech segment
    if in_speech:
        speech_end = len(is_speech)
        if speech_end - speech_start >= min_speech_frames:
            segments.append({
                'start': round(speech_start * 0.010, 4),
                'end': round(speech_end * 0.010, 4),
            })

    return segments
