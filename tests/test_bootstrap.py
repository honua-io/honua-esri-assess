import tomllib
from pathlib import Path

from honua_esri_assess import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_version_is_defined() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    assert __version__ == pyproject["project"]["version"]
