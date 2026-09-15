"""Model utterance interruptions in screen reader speech."""


def compute_heard_text(full_text, total_duration_ms, interrupted_at_ms):
    """Compute which words were fully articulated before interruption.

    Uses character-proportional timing: each character (including spaces)
    occupies total_duration_ms / len(full_text) milliseconds. A word is
    heard if its last character's end time <= interrupted_at_ms.

    Character at position p (0-indexed) ends at (p + 1) * time_per_char.
    """
    if not full_text:
        return ""
    if interrupted_at_ms >= total_duration_ms:
        return full_text
    if interrupted_at_ms <= 0:
        return ""

    n = len(full_text)
    time_per_char = total_duration_ms / n

    heard = []
    i = 0
    while i < n:
        # Skip spaces
        while i < n and full_text[i] == ' ':
            i += 1
        if i >= n:
            break
        # Find end of word
        j = i
        while j < n and full_text[j] != ' ':
            j += 1
        # Word spans positions i..j-1; last char at j-1 ends at j * time_per_char
        end_time = j * time_per_char
        if end_time < interrupted_at_ms:
            heard.append(full_text[i:j])
        else:
            break
        i = j

    return ' '.join(heard)
