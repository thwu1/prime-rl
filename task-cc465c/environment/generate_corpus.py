"""Generate deterministic test corpora for BPE optimization benchmarking."""
import random


words = [
    # Common English words
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "I",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "people", "into", "year", "your", "good", "some", "could", "them", "see",
    "other", "than", "then", "now", "look", "only", "come", "its", "over",
    "think", "also", "back", "after", "use", "two", "how", "our", "work",
    "first", "well", "way", "even", "new", "want", "because", "any", "these",
    "give", "day", "most", "us",
    # Words with accented characters (multi-byte UTF-8)
    "café", "naïve", "résumé", "über", "straße", "año", "señor",
    # Technical terms
    "algorithm", "tokenizer", "encoding", "compression", "frequency",
    "optimization", "implementation", "data", "structure", "function",
    "variable", "parameter", "iteration", "sequence", "dictionary",
    # Number words
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
]


def generate_corpus(seed, num_sentences, min_len, max_len):
    rng = random.Random(seed)
    sentences = []
    for _ in range(num_sentences):
        length = rng.randint(min_len, max_len)
        sentence = " ".join(rng.choice(words) for _ in range(length))
        sentences.append(sentence.capitalize() + ".")
    return "\n".join(sentences)


# Medium corpus (~50 KB)
medium = generate_corpus(seed=42, num_sentences=800, min_len=5, max_len=15)
with open("/app/corpus_medium.txt", "w") as f:
    f.write(medium)
print(f"Medium corpus: {len(medium)} chars, {len(medium.encode('utf-8'))} bytes")

# Large corpus (~640 KB)
large = generate_corpus(seed=123, num_sentences=12000, min_len=5, max_len=15)
with open("/app/corpus_large.txt", "w") as f:
    f.write(large)
print(f"Large corpus: {len(large)} chars, {len(large.encode('utf-8'))} bytes")
