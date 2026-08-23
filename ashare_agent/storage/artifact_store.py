from pathlib import Path, PurePosixPath


class FileSystemArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def key_for(self, path: str | Path) -> str:
        resolved = Path(path).expanduser().resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("artifact must be stored under the shared root") from exc
        return relative.as_posix()

    def resolve(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if key.is_absolute() or ".." in key.parts:
            raise ValueError("invalid artifact storage key")
        resolved = (self.root / Path(*key.parts)).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("invalid artifact storage key") from exc
        return resolved
