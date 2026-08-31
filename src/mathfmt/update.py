"""Check for MathFmt updates from GitHub Releases."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from ._version import __version__

GITHUB_API = "https://api.github.com/repos/Gmlleo/mathfmt/releases"
CACHE_FILE = Path.home() / ".cache" / "mathfmt" / "update-check.json"
CACHE_TTL = 3600  # 1 hour

# Required keys that every cache entry must contain.
_REQUIRED_CACHE_KEYS = frozenset({"checked_at", "latest_version", "is_update_available", "prerelease"})


def _parse_semver(version: str) -> tuple:
    """Parse a version string into a sortable tuple.

    Stable: ``(major, minor, patch, 1)``
    Prerelease: ``(major, minor, patch, 0) + segments``

    Each segment is a ``(kind_flag, value)`` pair where *kind_flag*
    is ``0`` for a numeric identifier and ``1`` for a string
    identifier.  Numeric identifiers sort before string identifiers
    (per SemVer 2.0), so ``1.0.0-alpha`` > ``1.0.0-1``.

    Build metadata (``+...``) is discarded.
    """
    v = version.lstrip("v")
    # Discard build metadata
    v = v.split("+", 1)[0]

    base, sep, prerelease_str = v.partition("-")
    parts = base.split(".")
    base_nums: list[int] = []
    for p in parts:
        try:
            base_nums.append(int(p))
        except ValueError:
            base_nums.append(0)

    if not sep:
        # Stable release — sentinel that sorts AFTER any prerelease
        return tuple(base_nums) + (1,)

    # Prerelease: segment the suffix
    segments: list[tuple[int, object]] = []
    for s in prerelease_str.split("."):
        try:
            segments.append((0, int(s)))  # numeric: kind=0 (lower priority)
        except ValueError:
            segments.append((1, s))  # string:  kind=1 (higher priority)

    return tuple(base_nums) + (0,) + tuple(segments)


def _load_cache(prerelease: bool) -> dict[str, Any] | None:
    """Load cached check result if still fresh and matching the prerelease mode."""
    try:
        if not CACHE_FILE.is_file():
            return None
        raw = CACHE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    # Guard against non-dict root (e.g. []) and type errors on .keys()
    if not isinstance(data, dict):
        return None
    try:
        if _REQUIRED_CACHE_KEYS - data.keys():
            return None
        if time.time() - data["checked_at"] >= CACHE_TTL:
            return None
    except (TypeError, KeyError):
        return None

    # Validate prerelease mode matches
    if data.get("prerelease") != prerelease:
        return None

    return data


def _save_cache(data: dict[str, Any]) -> None:
    """Save check result to cache."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # caching is best-effort


@dataclass
class UpdateInfo:
    """Information about an available update."""

    current_version: str
    latest_version: str
    is_update_available: bool
    release_url: str
    release_notes: str
    published_at: str
    install_commands: list[str]
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return f"MathFmt {self.current_version}: {self.error}"
        if not self.is_update_available:
            return f"MathFmt {self.current_version} is up to date."
        return f"MathFmt {self.latest_version} is available (you have {self.current_version})."


def fetch_latest_release(include_prerelease: bool = False) -> dict[str, Any] | None:
    """Fetch the latest release info from GitHub API.

    Returns the release dict, or None if the request fails.
    """
    url = GITHUB_API
    if include_prerelease:
        # list all releases and pick the first (which is latest)
        url += "?per_page=5"
    else:
        url += "/latest"

    try:
        req = Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "mathfmt-update-check")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError, OSError):
        return None

    if isinstance(data, list):
        # we got a list from /releases; filter prereleases if needed
        if not include_prerelease:
            data = [r for r in data if not r.get("prerelease", False)]
        if not data:
            return None
        return data[0]
    return data


def check_for_updates(
    include_prerelease: bool = False,
    force: bool = False,
) -> UpdateInfo:
    """Check GitHub for a newer MathFmt release.

    Args:
        include_prerelease: Also consider pre-release versions.
        force: Bypass the cache and hit GitHub directly.

    Returns an UpdateInfo with comparison results.  When the network is
    unreachable the returned info will have ``error`` set to a non-empty
    string and ``is_update_available`` will be ``False``.
    """
    current = __version__

    # Check cache first (unless forced)
    if not force:
        cached = _load_cache(prerelease=include_prerelease)
        if cached is not None:
            return UpdateInfo(
                current_version=current,
                latest_version=cached["latest_version"],
                is_update_available=cached["is_update_available"],
                release_url=cached.get("release_url", ""),
                release_notes=cached.get("release_notes", ""),
                published_at=cached.get("published_at", ""),
                install_commands=_build_install_commands(cached["latest_version"]),
            )

    release = fetch_latest_release(include_prerelease)

    if release is None:
        return UpdateInfo(
            current_version=current,
            latest_version=current,
            is_update_available=False,
            release_url="",
            release_notes="",
            published_at="",
            install_commands=[],
            error="Could not reach GitHub to check for updates.",
        )

    latest_tag = release.get("tag_name", current)
    latest_version = latest_tag.lstrip("v")
    is_update = _parse_semver(latest_version) > _parse_semver(current)

    info = UpdateInfo(
        current_version=current,
        latest_version=latest_version,
        is_update_available=is_update,
        release_url=release.get("html_url", ""),
        release_notes=release.get("body", ""),
        published_at=release.get("published_at", ""),
        install_commands=_build_install_commands(latest_version),
    )

    # Cache the result
    _save_cache(
        {
            "checked_at": time.time(),
            "latest_version": latest_version,
            "is_update_available": is_update,
            "prerelease": include_prerelease,
            "release_url": info.release_url,
            "release_notes": info.release_notes,
            "published_at": info.published_at,
        }
    )

    return info


def _build_install_commands(latest_version: str) -> list[str]:
    """Build platform-appropriate upgrade commands."""
    return [
        "pip install --upgrade mathfmt",
        f"pip install --upgrade mathfmt=={latest_version}",
        "pip install --upgrade git+https://github.com/Gmlleo/mathfmt.git",
    ]
