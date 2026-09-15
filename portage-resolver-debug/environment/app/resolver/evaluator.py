"""
Resolution strategy evaluator for Portage world upgrades.

Compares two upgrade strategies:
  - prefer_newest: always choose the highest available version per slot
  - minimize_rebuilds: prefer versions that preserve current subslots
    when a same-subslot newer version exists, reducing := rebuild cascades

Metrics per strategy:
  upgrades:        list of {cp, old_version, new_version}
  total_upgrades:  number of packages being version-upgraded
  slot_rebuilds:   number of packages needing := subslot rebuild
  newuse_rebuilds: number of packages needing USE-change rebuild
  total_merges:    total_upgrades + slot_rebuilds + newuse_rebuilds
"""

from .version import Version
from .solver import Resolver, Solution
from .depstring import evaluate


class StrategyEvaluator:
    """Compare resolution strategies for a world upgrade."""

    def __init__(self, db, config, installed):
        self.db = db
        self.config = config
        self.installed = installed

    def evaluate(self):
        """Compare prefer_newest vs minimize_rebuilds strategies.

        Returns dict:
            strategies:
                prefer_newest:      {upgrades, total_upgrades, slot_rebuilds,
                                     newuse_rebuilds, total_merges}
                minimize_rebuilds:  same keys
            recommended: strategy name with fewer total_merges
            rationale:   one-sentence explanation
        """
        # TODO: implement strategy evaluation
        return {
            'strategies': {
                'prefer_newest': {},
                'minimize_rebuilds': {}
            },
            'recommended': '',
            'rationale': ''
        }
