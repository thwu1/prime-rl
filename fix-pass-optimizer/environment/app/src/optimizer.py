
"""End-to-end compiler pass sequence optimization pipeline.

Ties together instruction counting, synergy graph construction, and
the genetic algorithm to search for pass sequences that minimize
instruction count in LLVM IR programs.
"""

import random
from src.instrcount import count_instructions
from src.synergy_graph import build_synergy_graph
from src.ga import Individual, initialize_population, select, crossover, mutate
from src.passes import AVAILABLE_PASSES, SYNERGY_PAIRS
from src.config import DEFAULT_CONFIG


def compute_improvement(baseline_count, optimized_count):
    """Compute the relative improvement over a baseline instruction count.

    A positive return value means the optimization reduced instruction count.

    Args:
        baseline_count: Instruction count without optimization.
        optimized_count: Instruction count after optimization.

    Returns:
        Fractional improvement (e.g. 0.2 means 20% reduction).
    """
    if baseline_count == 0:
        return 0.0
    return (optimized_count - baseline_count) / baseline_count


def evaluate_individual(individual, ir_file, baseline_count):
    """Evaluate an individual's fitness as the instruction count reduction.

    Fitness = baseline_count - optimized_count.  Higher is better.
    """
    opt_count = count_instructions(ir_file, individual.sequence)
    individual.fitness = baseline_count - opt_count
    return individual


def run_pipeline(ir_file, config=None):
    """Run the full optimization pipeline on an LLVM IR file.

    Args:
        ir_file: Path to the LLVM IR (.ll) file to optimize.
        config: Optional configuration dict overriding DEFAULT_CONFIG.

    Returns:
        Dict with keys: best_sequence, improvement, baseline_count,
        optimized_count, generations.
    """
    if config is None:
        config = dict(DEFAULT_CONFIG)

    random.seed(config.get("seed", 42))

    # Build synergy graph from empirical data
    graph = build_synergy_graph(SYNERGY_PAIRS)

    # Measure baseline instruction count (no optimization applied)
    baseline_count = count_instructions(ir_file, [])

    # Initialize population of candidate pass sequences
    population = initialize_population(
        graph, AVAILABLE_PASSES,
        pop_size=config["population_size"],
        min_length=config.get("min_length", 3),
        max_length=config.get("max_length", 15),
    )

    best_ever = None

    for gen in range(config["generations"]):
        # Evaluate fitness for every individual
        for ind in population:
            try:
                evaluate_individual(ind, ir_file, baseline_count)
            except RuntimeError:
                ind.fitness = 0

        # Track the best individual seen so far
        current_best = max(population, key=lambda x: x.fitness)
        if best_ever is None or current_best.fitness > best_ever.fitness:
            best_ever = Individual(
                sequence=list(current_best.sequence),
                fitness=current_best.fitness,
            )

        # Select parents for the next generation
        parents = select(population, config["selection_size"])

        # Breed next generation via crossover + mutation
        next_gen = []
        while len(next_gen) < config["population_size"]:
            p1, p2 = random.sample(parents, 2)
            c1_seq, c2_seq = crossover(p1.sequence, p2.sequence)
            c1_seq = mutate(c1_seq, graph, AVAILABLE_PASSES, config["mutation_rate"])
            c2_seq = mutate(c2_seq, graph, AVAILABLE_PASSES, config["mutation_rate"])
            next_gen.append(Individual(sequence=c1_seq))
            next_gen.append(Individual(sequence=c2_seq))

        population = next_gen[:config["population_size"]]

    # Compute final result
    if best_ever is None:
        return {
            "best_sequence": [],
            "improvement": 0.0,
            "baseline_count": 0,
            "optimized_count": 0,
            "generations": 0,
        }

    optimized_count = count_instructions(ir_file, best_ever.sequence)
    improvement = compute_improvement(baseline_count, optimized_count)

    return {
        "best_sequence": best_ever.sequence,
        "improvement": improvement,
        "baseline_count": baseline_count,
        "optimized_count": optimized_count,
        "generations": config["generations"],
    }
