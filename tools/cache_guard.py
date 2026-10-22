#!/usr/bin/env python3
"""Validate an explicitly authorized compile-cache target before any deletion.

Requires an existing container so both the resolved Compose definition and the actual
mount can be checked. Never follows a cache symlink or clears a running container's cache.
"""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys


def docker_json(*args, cwd=None):
    return json.loads(subprocess.check_output(["docker", *args], cwd=cwd, text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--target", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve(strict=True)
    target = Path(args.target)
    expected = project / "cache"
    if (not target.is_absolute() or target != expected or target.is_symlink()
            or target.resolve(strict=True) != expected or not target.is_dir()):
        raise ValueError("target must be the absolute, non-symlink project/cache directory")
    config = docker_json("compose", "config", "--format", "json", cwd=project)
    container, = docker_json("inspect", args.container)
    labels = container["Config"]["Labels"]
    if labels.get("com.docker.compose.project") != config["name"]:
        raise ValueError("container does not belong to the resolved Compose project")
    service = config["services"][labels["com.docker.compose.service"]]
    if service.get("environment", {}).get("HALOGEN_CACHE_DIR") != "/cache":
        raise ValueError("HALOGEN_CACHE_DIR must explicitly be /cache")
    mounts = [v for v in service.get("volumes", []) if v.get("target") == "/cache"]
    if (len(mounts) != 1 or mounts[0].get("type") != "bind"
            or mounts[0].get("source") != str(target)):
        raise ValueError("Compose cache mount does not match authorized target")
    actual = [m for m in container["Mounts"] if m["Destination"] == "/cache"]
    if (len(actual) != 1 or actual[0].get("Type") != "bind"
            or actual[0].get("Source") != str(target)):
        raise ValueError("actual container cache mount does not match authorized target")
    print(f"Authorized compile-cache contents: {target}", flush=True)
    if args.clear:
        if container["State"]["Running"]:
            raise ValueError("refusing to clear a running container's cache")
        # -xdev alone does not protect same-filesystem bind mounts. Refuse all nested
        # mounts, including bind mounts, before find can traverse them (Linux/Docker host).
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
            if mount.is_relative_to(target) and mount != target:
                raise ValueError("nested mount inside cache; refusing deletion")
        # GNU find does not follow symlinks, includes dotfiles, and stays on this filesystem.
        subprocess.run(["sudo", "-n", "find", str(target), "-xdev", "-mindepth", "1",
                        "-delete"], check=True)
        remaining = subprocess.check_output(
            ["sudo", "-n", "find", str(target), "-mindepth", "1", "-print", "-quit"], text=True)
        if remaining:
            raise ValueError("cache is not empty after clearing; refusing first-start timing")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"cache guard: {exc}")
