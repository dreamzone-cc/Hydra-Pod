import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydra_pod import cli, paths, quota, state_store
from hydra_pod.providers import registry
from hydra_pod.runtime import zcode
from hydra_pod.status import ProviderStatus, State, classify_failure


class ClassifyTests(unittest.TestCase):
    def test_known_failures(self):
        cases = {
            "Error: Model creation failed (traceId: x)": State.NOT_CONNECTED,
            "Error: Authorization timed out. Please retry login.": State.AUTH_FAILED,
            "Authorization Failed / 授权失败": State.AUTH_FAILED,
            '{"error":{"code":"1310","message":"Weekly/Monthly Limit Exhausted"}}': State.CONNECTED,
            "HTTP 401 Unauthorized": State.EXPIRED,
        }
        for text, state in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_failure(text)[0], state)

    def test_quota_is_connected_with_detail(self):
        state, detail = classify_failure("code 1308 usage limit")
        self.assertEqual((state, detail), (State.CONNECTED, "quota exhausted"))

    def test_unknown_failure_keeps_first_line(self):
        state, detail = classify_failure("boom happened\nstack...")
        self.assertEqual((state, detail), (State.AUTH_FAILED, "boom happened"))


class StateStoreTests(unittest.TestCase):
    def test_roundtrip_without_secrets(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(paths, "CACHE_DIR", Path(d)), \
             mock.patch.object(paths, "STATUS_CACHE", Path(d) / "status.json"):
            state_store.save(ProviderStatus("a", State.CONNECTED, model="m", verified=True))
            state_store.save(ProviderStatus("b", State.EXPIRED))
            loaded = state_store.load()
            self.assertEqual(loaded["a"].state, State.CONNECTED)
            self.assertTrue(loaded["a"].verified)
            self.assertEqual(loaded["b"].state, State.EXPIRED)
            self.assertEqual(set(json.loads((Path(d) / "status.json").read_text())["a"]),
                             {"provider", "state", "detail", "model", "checked_at", "verified"})


class RegistryTests(unittest.TestCase):
    def test_repo_providers_load(self):
        specs = registry.load_specs()
        self.assertIn("zcode-lite", specs)
        self.assertIn("opencode-go", specs)
        for p in registry.all_providers(specs):
            self.assertIsInstance(p.status(), ProviderStatus)

    def test_unknown_kind_is_listed_not_crashing(self):
        p = registry.get("x", {"x": {"kind": "future-thing"}})
        self.assertIsInstance(p, registry.Unimplemented)
        self.assertIn("not implemented", p.status().detail)

    def test_unknown_provider(self):
        with self.assertRaises(KeyError):
            registry.get("nope", {"x": {"kind": "opencode"}})


class RuntimeLocateTests(unittest.TestCase):
    def test_prefers_registered_desktop_entry(self):
        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "ZCode-3.14.3-linux-x64.AppImage"
            app.write_text("")
            entry = Path(d) / "zcode.desktop"
            entry.write_text(f'[Desktop Entry]\nExec="{app}" %U\n')
            with mock.patch.object(zcode, "DESKTOP_ENTRY", entry):
                self.assertEqual(zcode.find_appimage(), app)

    def test_falls_back_to_newest_version(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / "ZCode").mkdir()
            for v in ("3.9.0", "3.14.3", "3.11.2"):
                (home / "ZCode" / f"ZCode-{v}-linux-x64.AppImage").write_text("")
            with mock.patch.object(zcode, "DESKTOP_ENTRY", home / "missing.desktop"), \
                 mock.patch.object(Path, "home", return_value=home):
                self.assertEqual(zcode.find_appimage().name, "ZCode-3.14.3-linux-x64.AppImage")

    def test_env_isolates_data_dir_but_keeps_home(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(paths, "ZCODE_HOME", Path(d) / "zh"):
            e = zcode.env({"HOME": "/home/real", "PATH": "/usr/bin"})
            self.assertEqual(e["ZCODE_DATA_BASE_DIR"], str(Path(d) / "zh"))
            self.assertEqual(e["HOME"], "/home/real")
            self.assertEqual(oct(os.stat(Path(d) / "zh").st_mode & 0o777), "0o700")


class PathsLegacyTests(unittest.TestCase):
    """XDG dirs move to hydra-pod, with a legacy fallback per directory."""

    def test_new_absent_legacy_present_uses_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "opus-manager").mkdir()          # legacy dir only
            self.assertEqual(paths.brand_dir(base), base / "opus-manager")

    def test_both_absent_uses_new(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            self.assertEqual(paths.brand_dir(base), base / "hydra-pod")

    def test_both_present_uses_new(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "opus-manager").mkdir()          # legacy dir
            (base / "hydra-pod").mkdir()
            self.assertEqual(paths.brand_dir(base), base / "hydra-pod")


class PathsWiringTests(unittest.TestCase):
    """The XDG constants are wired through _xdg + brand_dir, not just the helper."""

    def _reload_with(self, **xdg):
        patcher = mock.patch.dict(os.environ, {k: str(v) for k, v in xdg.items()}, clear=True)
        patcher.start()
        self.addCleanup(importlib.reload, paths)   # runs last, once the env is restored
        self.addCleanup(patcher.stop)              # runs first
        return importlib.reload(paths)

    def test_constants_prefer_new_dir_when_no_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            p = self._reload_with(XDG_DATA_HOME=base, XDG_CACHE_HOME=base, XDG_CONFIG_HOME=base)
            self.assertEqual(p.DATA_DIR, base / "hydra-pod")
            self.assertEqual(p.CACHE_DIR, base / "hydra-pod")
            self.assertEqual(p.CONFIG_DIR, base / "hydra-pod")

    def test_constants_fall_back_per_base_to_legacy_dir(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            data, cache, config = tmp / "data", tmp / "cache", tmp / "config"
            for base in (data, cache, config):
                (base / "opus-manager").mkdir(parents=True)   # legacy dir only
            p = self._reload_with(XDG_DATA_HOME=data, XDG_CACHE_HOME=cache, XDG_CONFIG_HOME=config)
            self.assertEqual(p.DATA_DIR, data / "opus-manager")      # legacy name
            self.assertEqual(p.CACHE_DIR, cache / "opus-manager")    # legacy name
            self.assertEqual(p.CONFIG_DIR, config / "opus-manager")  # legacy name


class QuotaKeyPathTests(unittest.TestCase):
    def test_default_key_comes_from_config_dir(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(paths, "CONFIG_DIR", Path(d)), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(quota.key_file(), Path(d) / "zai.key")

    def test_key_file_env_overrides_config_dir(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(paths, "CONFIG_DIR", Path(d) / "cfg"), \
             mock.patch.dict(os.environ, {"ZAI_KEY_FILE": str(Path(d) / "k")}, clear=True):
            self.assertEqual(quota.key_file(), Path(d) / "k")


class CliTests(unittest.TestCase):
    def test_status_does_not_overwrite_live_result(self):
        class P:
            id = "p"
            def status(self):
                return ProviderStatus("p", State.CONNECTED, detail="inferred", verified=False)
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(paths, "CACHE_DIR", Path(d)), \
             mock.patch.object(paths, "STATUS_CACHE", Path(d) / "s.json"), \
             mock.patch.object(registry, "get", return_value=P()):
            state_store.save(ProviderStatus("p", State.CONNECTED, detail="live", verified=True))
            with mock.patch("sys.stdout"):
                cli.main(["status", "p"])
            self.assertEqual(state_store.load()["p"].detail, "live")

    def test_disconnect_refuses_noninteractive_without_yes(self):
        class P:
            id = "p"
            def disconnect_warning(self):
                return "affects the desktop app"
            def disconnect(self):
                raise AssertionError("must not disconnect")
        with mock.patch.object(registry, "get", return_value=P()), \
             mock.patch.object(sys.stdin, "isatty", return_value=False):
            self.assertEqual(cli.main(["disconnect", "p"]), 2)


if __name__ == "__main__":
    unittest.main()
