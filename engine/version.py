"""Engine version loaded from the repository VERSION file at startup."""

from pathlib import Path
import re


_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def load_engine_version() -> str:
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip()
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"VERSION must contain a semantic version, got {version!r}")
    return version


ENGINE_VERSION = load_engine_version()
