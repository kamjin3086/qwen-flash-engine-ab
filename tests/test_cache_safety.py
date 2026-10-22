"""Cache-safety CLI tests; only temporary directories and fake host commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class CacheSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.cache = self.project / "cache"
        self.cache.mkdir(parents=True)
        (self.cache / "keep").write_text("cached data")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "HALOGEN_DIR": str(self.project)}
        self.fake("docker", f'echo docker >> "{self.calls}"\nexit 99')
        self.fake("sudo", f'echo sudo >> "{self.calls}"\nexit 99')

    def fake(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def guard(self, *, clear=False, source=None, running=False):
        source = str(source or self.cache)
        config = {"name": "benchmark", "services": {"engine": {
            "environment": {"HALOGEN_CACHE_DIR": "/cache"},
            "volumes": [{"type": "bind", "source": source, "target": "/cache"}]}}}
        inspect = [{"Config": {"Labels": {"com.docker.compose.project": "benchmark",
                    "com.docker.compose.service": "engine"}},
                    "State": {"Running": running}, "Mounts": [
            {"Type": "bind", "Source": source, "Destination": "/cache"}]}]
        config_file = self.root / "config.json"
        inspect_file = self.root / "inspect.json"
        config_file.write_text(json.dumps(config))
        inspect_file.write_text(json.dumps(inspect))
        self.fake("docker", f'case "$1" in\ncompose) cat "{config_file}";;\ninspect) cat "{inspect_file}";;\n*) exit 99;;\nesac')
        return subprocess.run([sys.executable, str(REPO / "tools/cache_guard.py"),
                               "--project", str(self.project), "--container", "benchmark-engine",
                               "--target", str(self.cache), "--clear" if clear else "--check"],
                              env=self.env, capture_output=True, text=True)

    def test_clear_failure_is_fatal_and_preserves_data(self):
        p = self.guard(clear=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("cache guard", p.stderr)
        self.assertTrue((self.cache / "keep").exists())

    def test_runner_stops_before_startup_when_cleanup_fails(self):
        self.assertEqual(self.guard().returncode, 0)
        self.fake("docker", f'''echo "$*" >> "{self.calls}"
case "$1 $2" in
  "compose config") cat "{self.root / 'config.json'}";;
  "compose stop") exit 0;;
  "inspect "*) cat "{self.root / 'inspect.json'}";;
  "image inspect") echo digest;;
  "images "*) exit 0;;
  *) exit 99;;
esac''')
        self.fake("sleep", "exit 0")
        shutil.copy2(REPO / "bench.sh", self.root / "bench.sh")
        (self.root / "tools").mkdir()
        shutil.copy2(REPO / "tools/cache_guard.py", self.root / "tools/cache_guard.py")
        (self.project / "docker-compose.s1.yml").write_text(
            "image: ghcr.io/yamz-labs/kyojin-qwen@sha256:fixture\n")
        p = subprocess.run(["bash", str(self.root / "bench.sh"), "halogen", "--clear-cache",
                            str(self.cache)], env={**self.env, "KYOJIN_DIR": str(self.project)},
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("cache clearing failed; no first-start timing", p.stdout)
        self.assertNotIn("compose up", self.calls.read_text())
        self.assertFalse((self.root / "runs/halogen/startup.txt").exists())
        self.assertTrue((self.cache / "keep").exists())

    def test_running_container_is_never_cleared(self):
        p = self.guard(clear=True, running=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("running", p.stderr)
        self.assertFalse(self.calls.exists())

    def test_authorized_stopped_cache_is_cleared_including_dotfiles(self):
        (self.cache / ".hidden").write_text("cache")
        outside = self.root / "outside"
        outside.write_text("untouched")
        (self.cache / "link").symlink_to(outside)
        self.fake("sudo", 'shift\nexec "$@"')
        p = self.guard(clear=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertEqual(outside.read_text(), "untouched")

    def test_symlink_cache_is_refused(self):
        other = self.project / "other"
        self.cache.rename(other)
        self.cache.symlink_to(other, target_is_directory=True)
        p = self.guard(clear=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("non-symlink", p.stderr)
        self.assertTrue((other / "keep").exists())

    def test_mount_mismatch_refuses_deletion(self):
        p = self.guard(clear=True, source=self.project / "other")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("mount", p.stderr)
        self.assertFalse(self.calls.exists())
        self.assertTrue((self.cache / "keep").exists())

    def test_halogen_without_explicit_cache_authorization_does_not_touch_host(self):
        shutil.copy2(REPO / "bench.sh", self.root / "bench.sh")
        p = subprocess.run(["bash", str(self.root / "bench.sh"), "halogen"],
                           env=self.env, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--clear-cache", p.stdout + p.stderr)
        self.assertFalse(self.calls.exists(), "must refuse before any Docker or sudo call")
        self.assertEqual((self.cache / "keep").read_text(), "cached data")


if __name__ == "__main__":
    unittest.main()
