"""Configuration loader."""
import yaml


def load_config(path='/app/system_config.yaml'):
    with open(path) as f:
        return yaml.safe_load(f)
