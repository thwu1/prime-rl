"""Generate a deterministic training corpus for BPE optimization benchmarking."""
import random

random.seed(42)

common_words = [
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
    "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
    "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know",
    "take", "people", "into", "year", "your", "good", "some", "could",
    "them", "see", "other", "than", "then", "now", "look", "only", "come",
    "its", "over", "think", "also", "back", "after", "use", "two", "how",
    "our", "work", "first", "well", "way", "even", "new", "want", "because",
    "any", "these", "give", "day", "most", "us", "great", "between", "need",
    "large", "often", "system", "program", "number", "world", "still",
    "every", "should", "begin", "those", "thing", "water", "three", "later",
    "given", "along", "young", "house", "early", "child", "point", "right",
    "small", "group", "place", "while", "where", "might", "under", "never",
    "again", "power", "learn", "state", "through", "before", "many", "being",
    "same", "different", "important", "each", "during", "long", "very", "call",
    "much", "keep", "last", "tell", "change", "hand", "help", "show", "turn",
    "own", "run", "move", "start", "try", "ask", "next", "high", "end",
    "line", "part", "name", "left", "head", "read", "land", "side", "open",
]

sentences = []
for _ in range(10000):
    length = random.randint(5, 20)
    words = []
    for _ in range(length):
        idx = min(int(random.expovariate(0.025)), len(common_words) - 1)
        words.append(common_words[idx])
    sentence = " ".join(words)
    sentence = sentence[0].upper() + sentence[1:]
    punct = random.choice([".", ".", ".", "!", "?", ";"])
    sentence += punct
    if random.random() < 0.1:
        sentence += " " + str(random.randint(0, 99999))
    sentences.append(sentence)

corpus = "\n".join(sentences)

# Add repeated patterns that create interesting BPE merge opportunities
corpus += "\n" + "abracadabra " * 500
corpus += "\n" + "the quick brown fox jumps over the lazy dog\n" * 100
# Add some content with overlapping byte patterns
corpus += "\n" + "aaaaabbbbbccccc " * 200
corpus += "\n" + "xyxyxyxyxy " * 300

with open("/app/data/corpus.txt", "w") as f:
    f.write(corpus)

size = len(corpus.encode("utf-8"))
print(f"Corpus generated: {size} bytes")
