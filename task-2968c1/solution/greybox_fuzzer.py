"""
Coverage-guided greybox fuzzer with AFL-style exponential power schedule.
"""
import random
import hashlib
import pickle


# Characters biased toward programming constructs
_INTERESTING = list(
    '0123456789'
    '+-*/%=<>!'
    '()";, \\\''
    'abcdefghijklmnopqrstuvwxyz'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '_.\n\t'
)


class Seed:
    """Represent a fuzzer input with coverage and energy metadata."""

    def __init__(self, data, coverage=None, energy=1.0):
        self.data = data
        self.coverage = coverage if coverage is not None else frozenset()
        self.energy = energy
        self._pid = None

    @property
    def path_id(self):
        if self._pid is None:
            self._pid = get_path_id(self.coverage)
        return self._pid


def get_path_id(coverage):
    """Hash a coverage set to a unique path identifier."""
    pickled = pickle.dumps(sorted(coverage))
    return hashlib.md5(pickled).hexdigest()


class AFLFastSchedule:
    """Exponential power schedule: rare paths get exponentially more energy."""

    def __init__(self, exponent=5.0):
        self.exponent = exponent
        self.path_frequency = {}

    def assign_energy(self, population):
        """Set energy = 1 / (path_frequency ** exponent) for each seed."""
        for seed in population:
            freq = self.path_frequency.get(seed.path_id, 1)
            seed.energy = 1.0 / (freq ** self.exponent)

    def normalized_energy(self, population):
        """Return list of probabilities proportional to energy."""
        energies = [s.energy for s in population]
        total = sum(energies)
        if total == 0:
            n = len(population)
            return [1.0 / n] * n
        return [e / total for e in energies]

    def choose(self, population):
        """Select a seed weighted by normalized energy."""
        self.assign_energy(population)
        weights = self.normalized_energy(population)
        return random.choices(population, weights=weights, k=1)[0]


class GreyboxFuzzer:
    """Coverage-guided greybox fuzzer with byte-level mutation."""

    def __init__(self, seeds, schedule):
        self.seeds = list(seeds)
        self.schedule = schedule
        self.population = []
        self._seen_pids = set()
        self.failures = []

    def _rand_char(self):
        """Return a random character biased toward program-relevant chars."""
        if random.random() < 0.7:
            return random.choice(_INTERESTING)
        return chr(random.randint(32, 126))

    def mutate(self, inp):
        """Apply a random byte-level mutation to inp."""
        if len(inp) == 0:
            return self._rand_char()

        method = random.choice([
            'flip', 'flip', 'insert', 'delete', 'replace', 'replace'
        ])

        if method == 'flip':
            pos = random.randint(0, len(inp) - 1)
            return inp[:pos] + self._rand_char() + inp[pos + 1:]

        if method == 'insert':
            pos = random.randint(0, len(inp))
            return inp[:pos] + self._rand_char() + inp[pos:]

        if method == 'delete':
            if len(inp) <= 1:
                return inp
            pos = random.randint(0, len(inp) - 1)
            return inp[:pos] + inp[pos + 1:]

        if method == 'replace':
            pos = random.randint(0, len(inp) - 1)
            xor = random.randint(1, 15)
            code = ord(inp[pos]) ^ xor
            code = max(32, min(126, code))
            return inp[:pos] + chr(code) + inp[pos + 1:]

        return inp

    def create_candidate(self):
        """Select a seed from the population and apply stacked mutations."""
        if not self.population:
            base = random.choice(self.seeds)
        else:
            seed = self.schedule.choose(self.population)
            base = seed.data

        candidate = base
        # Geometric distribution: most candidates get 1-2 mutations
        n_mutations = 1
        while random.random() < 0.35 and n_mutations < 6:
            n_mutations += 1
        for _ in range(n_mutations):
            candidate = self.mutate(candidate)
            if len(candidate) > 256:
                candidate = candidate[:256]
        return candidate

    def run(self, run_func, num_iterations=10000):
        """Run the fuzzing loop.

        run_func(input_str) -> (coverage_frozenset, outcome_str, info_dict)
        outcome_str is 'pass' or 'fail'.

        Returns list of failure dicts.
        """
        # Phase 1: process all seeds
        for seed_data in self.seeds:
            try:
                coverage, outcome, info = run_func(seed_data)
                self._process(seed_data, coverage, outcome, info)
            except Exception:
                continue

        # Phase 2: mutate and fuzz
        for _ in range(num_iterations):
            candidate = self.create_candidate()
            try:
                coverage, outcome, info = run_func(candidate)
                self._process(candidate, coverage, outcome, info)
            except Exception:
                continue

        return self.failures

    def _process(self, inp, coverage, outcome, info):
        """Update population, path frequencies, and failure list."""
        pid = get_path_id(coverage)
        self.schedule.path_frequency[pid] = \
            self.schedule.path_frequency.get(pid, 0) + 1

        # Use path_id for fast membership check instead of frozenset comparison
        if pid not in self._seen_pids:
            self._seen_pids.add(pid)
            self.population.append(Seed(inp, coverage=coverage))

        if outcome == 'fail':
            self.failures.append({
                'input': inp,
                'coverage': coverage,
                'info': info,
            })

    @property
    def coverages_seen(self):
        """Backward-compatible property returning seen path IDs."""
        return self._seen_pids
