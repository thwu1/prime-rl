
"""Genetic algorithm for compiler pass sequence optimization.

Implements selection, crossover, and mutation operators that operate on
sequences of LLVM optimization pass names, guided by a synergy graph
of empirically measured pass interactions.
"""

import random
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Individual:
    """A candidate pass sequence with its fitness score."""
    sequence: List[str]
    fitness: float = 0.0


def initialize_population(graph, available_passes, pop_size=50,
                           min_length=3, max_length=15):
    """Generate an initial population by walking the synergy graph.

    Starts from a random pass that has outgoing edges in the graph and
    follows edges to build sequences. Falls back to random passes when
    no graph neighbors are available.

    Args:
        graph: Synergy graph (dict of pass -> set of successors).
        available_passes: List of all valid pass names.
        pop_size: Number of individuals to create.
        min_length: Minimum sequence length.
        max_length: Maximum sequence length.

    Returns:
        List of Individual objects with uninitialized fitness.
    """
    population = []
    start_passes = list(graph.keys())
    if not start_passes:
        start_passes = available_passes

    for _ in range(pop_size):
        length = random.randint(min_length, max_length)
        sequence = []
        current = random.choice(start_passes)
        sequence.append(current)

        for _ in range(length - 1):
            successors = list(graph.get(current, set()))
            if not successors:
                current = random.choice(available_passes)
            else:
                current = random.choice(successors)
            sequence.append(current)

        population.append(Individual(sequence=sequence))

    return population


def select(population, k):
    """Select the top-k individuals by fitness.

    Args:
        population: List of Individual objects with evaluated fitness.
        k: Number of individuals to select.

    Returns:
        List of k individuals with the highest fitness values.
    """
    sorted_pop = sorted(population, key=lambda ind: ind.fitness)
    return sorted_pop[:k]


def crossover(parent1_seq, parent2_seq):
    """Single-point crossover at a common pass between two sequences.

    Finds passes that appear in both parents, picks one at random as the
    crossover point, and swaps the suffixes.

    Args:
        parent1_seq: First parent's pass sequence.
        parent2_seq: Second parent's pass sequence.

    Returns:
        Tuple of two child sequences.
    """
    common = set(parent1_seq) & set(parent2_seq)
    if not common:
        return list(parent1_seq), list(parent2_seq)

    crossover_pass = random.choice(list(common))
    idx1 = parent1_seq.index(crossover_pass)
    idx2 = parent2_seq.index(crossover_pass)

    child1 = list(parent1_seq[:idx1+1]) + list(parent2_seq[idx2:])
    child2 = list(parent2_seq[:idx2+1]) + list(parent1_seq[idx1:])

    return child1, child2


def mutate(sequence, graph, available_passes, mutation_rate=0.3):
    """Point mutation: replace individual passes with synergy-graph neighbors.

    For each position, with probability mutation_rate, replace the pass
    with a random successor from the synergy graph (or a random pass if
    no successors exist).

    Args:
        sequence: The pass sequence to mutate.
        graph: Synergy graph for finding valid replacements.
        available_passes: Fallback list of valid pass names.
        mutation_rate: Per-position probability of mutation.

    Returns:
        A new (possibly mutated) sequence.
    """
    mutated = list(sequence)
    for i in range(len(mutated)):
        if random.random() < mutation_rate:
            successors = list(graph.get(mutated[i], set()))
            if successors:
                mutated[i] = random.choice(successors)
            else:
                mutated[i] = random.choice(available_passes)
    return mutated
