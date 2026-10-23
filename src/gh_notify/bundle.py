"""Build a small .app bundle that runs this program with its own identity.

macOS decides who a notification comes from using the bundle of the running process.
A bare Python interpreter has no bundle, so its notifications are silently dropped.
The launcher in this bundle loads libpython into its own process (no fork or exec), so
the process reports the bundle's identifier and notifications are delivered.
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path

import gh_notify

BUNDLE_ID = "com.gillespied.gh-notify"
APP_NAME = "GH Notify"
APP_PATH = Path.home() / "Applications" / f"{APP_NAME}.app"
LAUNCHER_NAME = "gh-notify-launcher"
ENTRY_CODE = "from gh_notify import main; main()"

LAUNCHER_SOURCE = r"""
// usage: launcher LIBPYTHON PYTHONHOME PYTHONPATH python-args...
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

typedef int (*py_bytes_main_t)(int, char **);

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: %s LIBPYTHON PYTHONHOME PYTHONPATH python-args...\n", argv[0]);
        return 2;
    }
    setenv("PYTHONHOME", argv[2], 1);
    setenv("PYTHONPATH", argv[3], 1);
    void *handle = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }
    py_bytes_main_t py_main = (py_bytes_main_t)dlsym(handle, "Py_BytesMain");
    if (!py_main) {
        fprintf(stderr, "Py_BytesMain not found\n");
        return 1;
    }
    argv[3] = argv[0];  // becomes Python's program name
    return py_main(argc - 3, argv + 3);
}
"""


class BundleError(Exception):
    """Raised when the app bundle cannot be built."""


@dataclass(frozen=True)
class PythonRuntime:
    """What the launcher needs to start the current interpreter and packages."""

    libpython: Path
    home: Path
    path: str


def libpython_candidates(
    home: Path, ldlibrary: str, libdir: str, version: str
) -> list[Path]:
    """Places the shared Python library can be, most specific first.

    uv-managed Python keeps a bare filename in `lib/` (`libpython3.13.dylib`).
    Homebrew's framework build reports `LDLIBRARY` relative to the framework root
    (`Python.framework/Versions/3.14/Python`), and the real file is `<home>/Python`.
    """
    candidates = []
    if ldlibrary:
        candidates += [home / "lib" / ldlibrary, home / Path(ldlibrary).name]
    if libdir:
        candidates.append(Path(libdir) / f"libpython{version}.dylib")
    candidates.append(home / "lib" / f"libpython{version}.dylib")
    return list(dict.fromkeys(candidates))


def find_libpython(home: Path, ldlibrary: str, libdir: str, version: str) -> Path:
    """Return the first existing library, or raise listing every place that was tried."""
    candidates = libpython_candidates(home, ldlibrary, libdir, version)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    tried = "\n  ".join(str(c) for c in candidates)
    raise BundleError(f"libpython not found. Looked in:\n  {tried}")


def current_runtime() -> PythonRuntime:
    """Describe the interpreter and package locations of the running environment."""
    home = Path(sys.base_prefix)
    libpython = find_libpython(
        home,
        sysconfig.get_config_var("LDLIBRARY") or "",
        sysconfig.get_config_var("LIBDIR") or "",
        sysconfig.get_python_version(),
    )
    site_packages = sysconfig.get_paths()["purelib"]
    package_root = str(Path(gh_notify.__file__).resolve().parent.parent)
    entries = list(dict.fromkeys([site_packages, package_root]))
    return PythonRuntime(libpython=libpython, home=home, path=":".join(entries))


def build_info_plist() -> dict:
    """Return the bundle's Info.plist contents."""
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": LAUNCHER_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,
    }


def launcher_path(app_path: Path = APP_PATH) -> Path:
    """Path of the launcher executable inside the bundle."""
    return app_path / "Contents" / "MacOS" / LAUNCHER_NAME


def program_arguments(launcher: Path, runtime: PythonRuntime, *args: str) -> list[str]:
    """Full command line that starts the app through the launcher."""
    return [
        str(launcher),
        str(runtime.libpython),
        str(runtime.home),
        runtime.path,
        "-c",
        ENTRY_CODE,
        *args,
    ]


def build_bundle(app_path: Path = APP_PATH) -> Path:
    """Create or update the bundle, returning the launcher path.

    The launcher is only recompiled when missing or when its source changed, because
    a new binary hash can make macOS ask for notification permission again.
    """
    launcher = launcher_path(app_path)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    (app_path / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(build_info_plist())
    )

    marker = app_path / "Contents" / "Resources" / "launcher-source.c"
    marker.parent.mkdir(parents=True, exist_ok=True)
    stale = not marker.exists() or marker.read_text() != LAUNCHER_SOURCE
    if not launcher.exists() or stale:
        _compile(launcher)
        marker.write_text(LAUNCHER_SOURCE)
        _run(
            ["codesign", "--force", "--sign", "-", str(app_path)], "sign the app bundle"
        )
    return launcher


def remove_bundle(app_path: Path = APP_PATH) -> None:
    """Delete the bundle if present."""
    shutil.rmtree(app_path, ignore_errors=True)


def _compile(output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "launcher.c"
        source.write_text(LAUNCHER_SOURCE)
        _run(["clang", "-O2", "-o", str(output), str(source)], "compile the launcher")


def _run(cmd: list[str], what: str) -> None:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BundleError(
            f"Cannot {what}: {cmd[0]} not found. Run 'xcode-select --install'."
        ) from exc
    if result.returncode != 0:
        raise BundleError(f"Cannot {what}: {result.stderr.strip()}")
