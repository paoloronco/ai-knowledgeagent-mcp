"""Non-removable exclusions from the bundled indexing policy."""

from pathlib import Path

import yaml


DEFAULT_POLICY = yaml.safe_load(Path(__file__).with_name("index-policy.yaml").read_text(encoding="utf-8"))
REQUIRED_DIRECTORY_NAMES = frozenset(name.casefold() for name in DEFAULT_POLICY["exclude_directories"])
REQUIRED_TOP_LEVEL_NAMES = frozenset(name.casefold() for name in DEFAULT_POLICY["exclude_top_level"])


def ensure_required_exclusions(policy):
    """Add missing bundled exclusions to a saved or custom policy in place."""
    if not isinstance(policy, dict):
        raise ValueError("Policy must be a YAML object")
    changed = False
    for key in ("exclude_directories", "exclude_top_level", "exclude_extensions"):
        values = policy.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{key} must be a list")
        values = list(values)
        present = {value if key == "exclude_extensions" else value.casefold() for value in values}
        for required in DEFAULT_POLICY[key]:
            normalized = required if key == "exclude_extensions" else required.casefold()
            if normalized not in present:
                values.append(required)
                present.add(normalized)
                changed = True
        policy[key] = values
    return changed
