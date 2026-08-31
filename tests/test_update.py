from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from mathfmt.update import (
    UpdateInfo,
    _build_install_commands,
    _load_cache,
    _parse_semver,
    _save_cache,
    check_for_updates,
    fetch_latest_release,
)

# ── _parse_semver ──────────────────────────────────────────────────


class TestParseSemver:
    def test_stable(self) -> None:
        # Stable versions carry a (1,) sentinel
        assert _parse_semver("0.2.0") == (0, 2, 0, 1)
        assert _parse_semver("1.0.0") == (1, 0, 0, 1)
        assert _parse_semver("0.10.5") == (0, 10, 5, 1)

    def test_with_v_prefix(self) -> None:
        assert _parse_semver("v0.2.0") == (0, 2, 0, 1)
        assert _parse_semver("v1.0.0") == (1, 0, 0, 1)

    def test_ordering_stable(self) -> None:
        assert _parse_semver("0.2.0") > _parse_semver("0.1.0")
        assert _parse_semver("0.10.0") > _parse_semver("0.2.0")
        assert _parse_semver("1.0.0") > _parse_semver("0.99.0")
        assert _parse_semver("0.2.0") == _parse_semver("v0.2.0")

    # ── pre-release ────────────────────────────────────────────────

    def test_stable_beats_prerelease(self) -> None:
        """1.0.0 > 1.0.0-alpha — stable always newer than prerelease."""
        assert _parse_semver("1.0.0") > _parse_semver("1.0.0-alpha")
        assert _parse_semver("1.0.0") > _parse_semver("1.0.0-beta")
        assert _parse_semver("1.0.0") > _parse_semver("1.0.0-rc.1")

    def test_prerelease_less_than_stable_same_base(self) -> None:
        """0.2.1-beta < 0.2.1 — prerelease always less."""
        assert _parse_semver("0.2.1-beta") < _parse_semver("0.2.1")

    def test_prerelease_labels_compared(self) -> None:
        """alpha < beta < rc within same base version."""
        assert _parse_semver("1.0.0-alpha") < _parse_semver("1.0.0-beta")
        assert _parse_semver("1.0.0-beta") < _parse_semver("1.0.0-rc.1")
        assert _parse_semver("1.0.0-alpha.1") > _parse_semver("1.0.0-alpha")
        # Numeric segments sort BEFORE string segments (semver rule)
        assert _parse_semver("1.0.0-1") < _parse_semver("1.0.0-alpha")

    def test_prerelease_vs_higher_base_stable(self) -> None:
        """0.3.0 > 0.2.1-beta — higher base always wins."""
        assert _parse_semver("0.3.0") > _parse_semver("0.2.1-beta")

    def test_prerelease_not_newer_than_same_stable(self) -> None:
        """0.2.1-beta is NOT > 0.2.1 (prerelease < stable)."""
        assert not _parse_semver("0.2.1-beta") > _parse_semver("0.2.1")

    def test_prerelease_alpha_vs_beta_update(self) -> None:
        """Going from alpha to beta IS an update."""
        assert _parse_semver("1.0.0-beta") > _parse_semver("1.0.0-alpha")

    def test_build_metadata_discarded(self) -> None:
        """+001 etc. are ignored."""
        assert _parse_semver("1.0.0-alpha+001") == _parse_semver("1.0.0-alpha")
        assert _parse_semver("1.0.0+20130313144700") == _parse_semver("1.0.0")

    def test_malformed(self) -> None:
        # Malformed strings don't crash — they just degrade gracefully
        assert isinstance(_parse_semver("not-a-version"), tuple)
        assert isinstance(_parse_semver(""), tuple)
        # Pure nonsense → numeric part is all zeros
        assert _parse_semver("abc") == (0, 1)


# ── _build_install_commands ──────────────────────────────────────────


class TestBuildInstallCommands:
    def test_returns_list(self) -> None:
        cmds = _build_install_commands("0.3.0")
        assert len(cmds) == 3
        assert any("pip install --upgrade mathfmt" == c for c in cmds)
        assert any("0.3.0" in c for c in cmds)
        assert any("github.com" in c for c in cmds)

    def test_no_f_string_without_placeholders(self) -> None:
        cmds = _build_install_commands("0.3.0")
        assert all(isinstance(c, str) for c in cmds)


# ── UpdateInfo ─────────────────────────────────────────────────────


class TestUpdateInfo:
    def test_up_to_date(self) -> None:
        info = UpdateInfo(
            current_version="0.2.0",
            latest_version="0.2.0",
            is_update_available=False,
            release_url="",
            release_notes="",
            published_at="",
            install_commands=[],
        )
        assert "up to date" in info.summary

    def test_update_available(self) -> None:
        info = UpdateInfo(
            current_version="0.2.0",
            latest_version="0.3.0",
            is_update_available=True,
            release_url="https://github.com/...",
            release_notes="New features!",
            published_at="2026-06-21",
            install_commands=["pip install --upgrade mathfmt"],
        )
        assert "0.3.0 is available" in info.summary
        assert "you have 0.2.0" in info.summary

    def test_error_message_shown_in_summary(self) -> None:
        info = UpdateInfo(
            current_version="0.2.0",
            latest_version="0.2.0",
            is_update_available=False,
            release_url="",
            release_notes="",
            published_at="",
            install_commands=[],
            error="Could not reach GitHub to check for updates.",
        )
        assert "Could not reach GitHub" in info.summary


# ── fetch_latest_release ───────────────────────────────────────────


class TestFetchLatestRelease:
    def test_returns_none_on_network_error(self) -> None:
        with patch("mathfmt.update.urlopen", side_effect=OSError("no network")):
            assert fetch_latest_release() is None

    def test_returns_dict_on_success(self) -> None:
        fake_release = {
            "tag_name": "v0.3.0",
            "html_url": "https://github.com/.../releases/tag/v0.3.0",
            "body": "Release notes here.",
            "published_at": "2026-06-22T00:00:00Z",
            "prerelease": False,
        }
        with patch("mathfmt.update.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(fake_release).encode(
                "utf-8"
            )
            result = fetch_latest_release()
            assert result is not None
            assert result["tag_name"] == "v0.3.0"

    def test_filters_prereleases_in_list(self) -> None:
        releases = [
            {"tag_name": "v0.3.0-beta", "prerelease": True},
            {"tag_name": "v0.2.0", "prerelease": False},
        ]
        with patch("mathfmt.update.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(releases).encode(
                "utf-8"
            )
            result = fetch_latest_release(include_prerelease=False)
            assert result is not None
            assert result["tag_name"] == "v0.2.0"

    def test_include_prerelease_does_not_filter(self) -> None:
        releases = [
            {"tag_name": "v0.3.0-beta", "prerelease": True},
            {"tag_name": "v0.2.0", "prerelease": False},
        ]
        with patch("mathfmt.update.urlopen") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(releases).encode(
                "utf-8"
            )
            result = fetch_latest_release(include_prerelease=True)
            assert result is not None
            assert result["tag_name"] == "v0.3.0-beta"


# ── check_for_updates ─────────────────────────────────────────────


class TestCheckForUpdates:
    def test_network_failure_sets_error(self) -> None:
        with patch("mathfmt.update.fetch_latest_release", return_value=None):
            with patch("mathfmt.update._load_cache", return_value=None):
                info = check_for_updates(force=True)
                assert not info.is_update_available
                assert "Could not reach GitHub" in info.error

    def test_detects_newer_version(self) -> None:
        fake_release = {
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/.../releases/tag/v1.2.0",
            "body": "New release!",
            "published_at": "2026-06-22T00:00:00Z",
            "prerelease": False,
        }
        with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
            with patch("mathfmt.update._load_cache", return_value=None):
                with patch("mathfmt.update._save_cache"):
                    info = check_for_updates(force=True)
                    assert info.is_update_available
                    assert info.latest_version == "1.2.0"
                    assert "New release!" in info.release_notes

    def test_same_version_is_up_to_date(self) -> None:
        from mathfmt import __version__

        fake_release: dict[str, object] = {
            "tag_name": f"v{__version__}",
            "html_url": "",
            "body": "",
            "published_at": "",
            "prerelease": False,
        }
        with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
            with patch("mathfmt.update._load_cache", return_value=None):
                info = check_for_updates(force=True)
                assert not info.is_update_available

    def test_stable_not_updated_by_prerelease(self) -> None:
        """Running on 1.0.0, latest tag is 1.0.0-rc.1 — NOT an update."""
        fake_release = {
            "tag_name": "v1.0.0-rc.1",
            "html_url": "",
            "body": "",
            "published_at": "",
            "prerelease": True,
        }
        with patch("mathfmt.update.__version__", "1.0.0"):
            with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
                with patch("mathfmt.update._load_cache", return_value=None):
                    with patch("mathfmt.update._save_cache"):
                        info = check_for_updates(force=True)
                        assert not info.is_update_available, (
                            f"stable {info.current_version} should NOT see "
                            f"prerelease {info.latest_version} as newer"
                        )

    def test_prerelease_sees_newer_prerelease(self) -> None:
        """Running 1.0.0-alpha, latest is 1.0.0-beta — IS an update."""
        fake_release = {
            "tag_name": "v1.0.0-beta",
            "html_url": "",
            "body": "",
            "published_at": "",
            "prerelease": True,
        }
        with patch("mathfmt.update.__version__", "1.0.0-alpha"):
            with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
                with patch("mathfmt.update._load_cache", return_value=None):
                    with patch("mathfmt.update._save_cache"):
                        info = check_for_updates(force=True)
                        assert info.is_update_available

    def test_uses_cache_when_fresh(self) -> None:
        cached = {
            "checked_at": time.time(),
            "latest_version": "0.3.0",
            "is_update_available": True,
            "prerelease": False,
            "release_url": "",
            "release_notes": "",
            "published_at": "",
        }
        with patch("mathfmt.update._load_cache", return_value=cached):
            info = check_for_updates()
            assert info.is_update_available
            assert info.latest_version == "0.3.0"

    def test_bypasses_stale_cache(self) -> None:
        fake_release = {
            "tag_name": "v1.2.0",
            "html_url": "",
            "body": "",
            "published_at": "",
            "prerelease": False,
        }
        with patch("mathfmt.update._load_cache", return_value=None):
            with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
                with patch("mathfmt.update._save_cache"):
                    info = check_for_updates()
                    assert info.is_update_available
                    assert info.latest_version == "1.2.0"

    def test_prerelease_cache_isolated_from_stable(self, tmp_path: Path) -> None:
        prerelease_cache = {
            "checked_at": time.time(),
            "latest_version": "0.3.0-beta",
            "is_update_available": True,
            "prerelease": True,
            "release_url": "",
            "release_notes": "",
            "published_at": "",
        }
        fake_release = {
            "tag_name": "v0.2.0",
            "html_url": "",
            "body": "",
            "published_at": "",
            "prerelease": False,
        }
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps(prerelease_cache), encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", cache_path):
            with patch("mathfmt.update.fetch_latest_release", return_value=fake_release):
                with patch("mathfmt.update._save_cache"):
                    info = check_for_updates(include_prerelease=False)
                    assert info.latest_version == "0.2.0"


# ── _load_cache robustness ──────────────────────────────────────────


class TestCache:
    def test_load_cache_returns_none_for_missing_file(self) -> None:
        with patch.object(Path, "is_file", return_value=False):
            assert _load_cache(prerelease=False) is None

    def test_load_cache_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid", encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", bad_file):
            assert _load_cache(prerelease=False) is None

    def test_load_cache_returns_none_for_json_array(self, tmp_path: Path) -> None:
        """Cache root as [] should not crash on .keys()."""
        array_file = tmp_path / "array.json"
        array_file.write_text("[]", encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", array_file):
            assert _load_cache(prerelease=False) is None

    def test_load_cache_returns_none_for_json_primitive(self, tmp_path: Path) -> None:
        """Cache root as 'hello' should not crash."""
        prim_file = tmp_path / "prim.json"
        prim_file.write_text('"hello"', encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", prim_file):
            assert _load_cache(prerelease=False) is None

    def test_load_cache_validates_required_keys(self, tmp_path: Path) -> None:
        incomplete = {"checked_at": time.time()}
        cache_path = tmp_path / "incomplete.json"
        cache_path.write_text(json.dumps(incomplete), encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", cache_path):
            assert _load_cache(prerelease=False) is None

    def test_load_cache_rejects_wrong_prerelease_mode(self, tmp_path: Path) -> None:
        stable_cache = {
            "checked_at": time.time(),
            "latest_version": "0.3.0",
            "is_update_available": True,
            "prerelease": False,
            "release_url": "",
            "release_notes": "",
            "published_at": "",
        }
        cache_path = tmp_path / "stable.json"
        cache_path.write_text(json.dumps(stable_cache), encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", cache_path):
            assert _load_cache(prerelease=True) is None

    def test_load_cache_accepts_matching_prerelease_mode(self, tmp_path: Path) -> None:
        prerelease_cache = {
            "checked_at": time.time(),
            "latest_version": "0.3.0-beta",
            "is_update_available": True,
            "prerelease": True,
            "release_url": "",
            "release_notes": "",
            "published_at": "",
        }
        cache_path = tmp_path / "prerelease.json"
        cache_path.write_text(json.dumps(prerelease_cache), encoding="utf-8")
        with patch("mathfmt.update.CACHE_FILE", cache_path):
            result = _load_cache(prerelease=True)
            assert result is not None
            assert result["latest_version"] == "0.3.0-beta"

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        fake_data: dict[str, object] = {
            "checked_at": time.time(),
            "latest_version": "0.3.0",
            "is_update_available": True,
            "prerelease": False,
            "release_url": "https://example.com",
            "release_notes": "notes",
            "published_at": "2026-06-22",
        }
        with patch("mathfmt.update.CACHE_FILE", tmp_path / "cache.json"):
            _save_cache(fake_data)
            loaded = _load_cache(prerelease=False)
            assert loaded is not None
            assert loaded["latest_version"] == "0.3.0"
            assert loaded["is_update_available"] is True
