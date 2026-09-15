
import random
from typing import List
from request import Request


def generate_workload(
    num_requests: int = 500,
    seed: int = 42,
    arrival_rate: float = 30.0,
) -> List[Request]:
    """Generate a deterministic heavy-tailed workload with SLO tiers.

    Size distribution:
      70 % short   (input 10-100,    output 5-30    tokens)
      20 % medium  (input 200-800,   output 50-200  tokens)
      10 % long    (input 1000-3000, output 200-800  tokens)

    SLO tier assignment correlates with request size:
      Short:  60% tier-0,  30% tier-1,  10% tier-2
      Medium: 10% tier-0,  50% tier-1,  40% tier-2
      Long:    0% tier-0,  20% tier-1,  80% tier-2

    Inter-arrival times follow a Poisson process.
    """
    rng = random.Random(seed)
    requests: List[Request] = []
    t = 0.0  # ms

    for i in range(num_requests):
        t += rng.expovariate(arrival_rate) * 1000.0

        r = rng.random()
        if r < 0.70:
            inp = rng.randint(10, 100)
            out = rng.randint(5, 30)
            tr = rng.random()
            slo_tier = 0 if tr < 0.60 else (1 if tr < 0.90 else 2)
        elif r < 0.90:
            inp = rng.randint(200, 800)
            out = rng.randint(50, 200)
            tr = rng.random()
            slo_tier = 0 if tr < 0.10 else (1 if tr < 0.60 else 2)
        else:
            inp = rng.randint(1000, 3000)
            out = rng.randint(200, 800)
            tr = rng.random()
            slo_tier = 1 if tr < 0.20 else 2

        requests.append(Request(
            id=i,
            arrival_time=round(t, 4),
            input_tokens=inp,
            output_tokens=out,
            slo_tier=slo_tier,
        ))

    return requests
