from pathlib import Path

import pytest

from ashare_agent.storage import FileSystemArtifactStore


def test_artifact_store_uses_portable_relative_key(tmp_path):
    root = tmp_path / "shared-artifacts"
    chart = root / "charts" / "result.png"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"png")
    store = FileSystemArtifactStore(root)

    key = store.key_for(chart)

    assert key == "charts/result.png"
    assert store.resolve(key) == chart.resolve()


def test_artifact_store_rejects_paths_outside_shared_root(tmp_path):
    store = FileSystemArtifactStore(tmp_path / "shared-artifacts")

    with pytest.raises(ValueError, match="shared root"):
        store.key_for(tmp_path / "outside.png")
    with pytest.raises(ValueError, match="storage key"):
        store.resolve("../outside.png")
    with pytest.raises(ValueError, match="storage key"):
        store.resolve(str(Path("/") / "outside.png"))
