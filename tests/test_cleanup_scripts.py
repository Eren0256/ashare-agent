import os
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "cleanup-stop-application.sh",
    "cleanup-delete-application.sh",
    "cleanup-kubernetes-host.sh",
)


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_cleanup_script_defaults_to_dry_run(script_name: str) -> None:
    result = subprocess.run(
        [str(PROJECT_ROOT / "scripts" / script_name)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "DRY RUN" in result.stdout
    assert "--execute" in result.stdout


@pytest.mark.parametrize("script_name", SCRIPTS)
def test_cleanup_script_rejects_unknown_argument(script_name: str) -> None:
    result = subprocess.run(
        [str(PROJECT_ROOT / "scripts" / script_name), "--unknown"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Usage:" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root guard requires a non-root test user")
@pytest.mark.parametrize(
    "script_name",
    ("cleanup-delete-application.sh", "cleanup-kubernetes-host.sh"),
)
def test_destructive_cleanup_requires_root(script_name: str) -> None:
    result = subprocess.run(
        [str(PROJECT_ROOT / "scripts" / script_name), "--execute"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "must run as root" in result.stderr
