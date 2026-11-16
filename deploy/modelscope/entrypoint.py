"""ModelScope-specific bootstrap; application source stays deployment-independent."""
from __future__ import annotations

import os
from pathlib import Path
import sys


SERVICE_UID = 10001
SERVICE_GID = 10001


def prepare_data(persistent_directory: Path, persistence_root: Path = Path("/mnt/workspace")) -> Path:
    """Initialize only this application's mounted directory; never the mount root."""
    if not persistent_directory.is_absolute():
        raise RuntimeError("STUDIO_DATA_DIR must be an absolute persistent directory.")
    base = persistence_root.resolve()
    target = persistent_directory.resolve()
    if target == base or not target.is_relative_to(base):
        raise RuntimeError("STUDIO_DATA_DIR must be a dedicated subdirectory of /mnt/workspace.")
    # The mounted base can itself be a platform symlink; descendants cannot.
    lexical = persistent_directory.absolute()
    for candidate in [lexical, *lexical.parents]:
        if candidate == persistence_root.absolute():
            break
        if candidate.is_symlink():
            raise RuntimeError("Persistent data directory must not contain symlinked descendants.")
    for directory in [target, target / "media", target / "generated"]:
        if directory.is_symlink():
            raise RuntimeError("Persistent media directories must not be symbolic links.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(directory, SERVICE_UID, SERVICE_GID)
    return target


def check_writable(target: Path) -> None:
    """Check after dropping privileges so root access cannot hide a mount problem."""
    probe = target / (".startup-write-check-" + str(os.getpid()))
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        probe.unlink()
    except OSError:
        raise RuntimeError(
            "Persistent data directory is not writable. Grant container UID/GID "
            "10001:10001 access to STUDIO_DATA_DIR; startup stopped."
        ) from None


def drop_privileges() -> None:
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(SERVICE_GID)
        os.setuid(SERVICE_UID)
    if os.geteuid() != SERVICE_UID or os.getegid() != SERVICE_GID:
        raise RuntimeError("Application must run as UID/GID 10001:10001 after initialization.")


def main() -> None:
    os.umask(0o077)
    root = Path(__file__).resolve().parents[2]
    directory = Path(os.environ.get("STUDIO_DATA_DIR", "/mnt/workspace/huawei-pc-content-studio"))
    try:
        target = prepare_data(directory)
        drop_privileges()
        check_writable(target)
    except (OSError, RuntimeError) as error:
        # These errors contain path/permission diagnostics, never credential values.
        print(f"Startup stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    os.chdir(root)
    os.execv(sys.executable, [
        sys.executable, "-m", "uvicorn", "huawei_agent.app:app",
        "--host", "0.0.0.0", "--port", "7860", "--workers", "1",
        "--no-access-log", "--timeout-keep-alive", "10",
    ])


if __name__ == "__main__":
    main()
