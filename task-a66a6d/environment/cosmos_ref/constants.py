# ═══════════════════════════════════════════════════════════════
# REFERENCE ONLY — Astronomer Cosmos constants and enumerations.
# Defines dbt resource types and test behavior modes.
# Will not run standalone (requires Cosmos framework).
# ═══════════════════════════════════════════════════════════════

from enum import Enum


class TestBehavior(Enum):
    """
    Behavior of the tests.
    """
    BUILD = "build"
    NONE = "none"
    AFTER_EACH = "after_each"
    AFTER_ALL = "after_all"


class DbtResourceType(Enum):
    """
    Type of dbt node.
    """
    MODEL = "model"
    SNAPSHOT = "snapshot"
    SEED = "seed"
    TEST = "test"
    SOURCE = "source"
    EXPOSURE = "exposure"


# According to the dbt documentation (https://docs.getdbt.com/reference/commands/build),
# build also supports test nodes. However, in the context of Cosmos, we will run test
# nodes together with the respective models/seeds/snapshots nodes.
SUPPORTED_BUILD_RESOURCES = [
    DbtResourceType.MODEL,
    DbtResourceType.SNAPSHOT,
    DbtResourceType.SEED,
]

# dbt test runs tests defined on models, sources, snapshots, and seeds.
# It expects that you have already created those resources through the appropriate commands.
# https://docs.getdbt.com/reference/commands/test
TESTABLE_DBT_RESOURCES = {
    DbtResourceType.MODEL,
    DbtResourceType.SOURCE,
    DbtResourceType.SNAPSHOT,
    DbtResourceType.SEED,
}
