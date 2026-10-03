"""Shared path and policy checks for the host document companion."""

import ntpath
import posixpath
from pathlib import PurePosixPath


def host_root(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c in value for c in "\x00\r\n"):
        raise ValueError("Enter an absolute host folder path")
    if ntpath.isabs(value) and ("\\" in value or ":" in value):
        normalized = ntpath.normpath(value)
        if normalized == ntpath.splitdrive(normalized)[0] + "\\":
            raise ValueError("Choose a folder, not a filesystem root")
    elif posixpath.isabs(value):
        normalized = posixpath.normpath(value)
        if normalized == "/":
            raise ValueError("Choose a folder, not a filesystem root")
    else:
        raise ValueError("Enter an absolute host folder path")
    return normalized


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(c in value for c in "\\\x00\r\n:"):
        raise ValueError("Invalid document path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Invalid document path")
    return path


def allowed_file(value, size, policy):
    path = relative_path(value)
    if type(size) is not int or size < 1 or size > policy["max_file_size_mb"] * 1024 * 1024:
        return False
    parts = path.parts
    if parts[0].casefold() in {x.casefold() for x in policy["exclude_top_level"]}:
        return False
    if any(x.casefold() in {y.casefold() for y in policy["exclude_directories"]} for x in parts[:-1]):
        return False
    excluded = {x.casefold() for x in policy.get("exclude_files", [])}
    if path.name.casefold() in excluded or value.casefold() in excluded:
        return False
    suffix = path.suffix.lower()
    return suffix in policy["include_extensions"] and suffix not in policy["exclude_extensions"]
