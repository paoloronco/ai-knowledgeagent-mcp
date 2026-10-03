"""Non-removable exclusions from the bundled indexing policy."""

import hashlib
from pathlib import Path

import yaml


DEFAULT_POLICY = yaml.safe_load(Path(__file__).with_name("index-policy.yaml").read_text(encoding="utf-8"))
REQUIRED_DIRECTORY_NAMES = frozenset(name.casefold() for name in DEFAULT_POLICY["exclude_directories"])
REQUIRED_TOP_LEVEL_NAMES = frozenset(name.casefold() for name in DEFAULT_POLICY["exclude_top_level"])

# Fingerprint of the former bundled directory list. Keep its values out of
# published source and images while upgrading policies stored in Docker volumes.
LEGACY_DIRECTORY_LIST_SHA256 = "675cb220b225d0b800c1dc8998ba158583b8077b38aafd3ac3c1c140f366970c"
LEGACY_DIRECTORY_COUNT = 16


def remove_legacy_default_exclusions(policy):
    """Remove only the former bundled additions, preserving later custom entries."""
    values = policy.get("exclude_directories") if isinstance(policy, dict) else None
    if not isinstance(values, list) or len(values) < LEGACY_DIRECTORY_COUNT or not all(isinstance(value, str) for value in values):
        return False
    prefix = values[:LEGACY_DIRECTORY_COUNT]
    if hashlib.sha256("\0".join(prefix).encode("utf-8")).hexdigest() != LEGACY_DIRECTORY_LIST_SHA256:
        return False
    policy["exclude_directories"] = list(DEFAULT_POLICY["exclude_directories"]) + values[LEGACY_DIRECTORY_COUNT:]
    return True


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
