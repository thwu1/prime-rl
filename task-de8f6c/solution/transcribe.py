"""Speech-to-text using OpenAI Whisper."""


def transcribe_audio(audio_path, model_name='tiny.en'):
    """Transcribe a WAV file using OpenAI Whisper.

    Parameters
    ----------
    audio_path : str
        Path to the WAV file.
    model_name : str
        Whisper model name (e.g. 'tiny.en', 'base.en').

    Returns
    -------
    str
        Transcribed text.
    """
    import whisper

    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path)
    return result['text'].strip()
