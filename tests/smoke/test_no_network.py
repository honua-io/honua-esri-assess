"""Network-isolation guard for the fixture-backed smoke suite.

Even though every smoke test installs a ``responses`` registry that intercepts
the ``requests`` session, this test enforces the *structural* guarantee that the
scanner never opens a real TCP socket. Any code path that bypasses ``requests``
(e.g. a stray ``urllib.request.urlopen``) gets caught here.

This is the project's enforcement of "network telemetry must be explicit and off
by default."
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from honua_esri_assess.cli import main as cli_main


@pytest.fixture
def block_real_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    real_socket_init = socket.socket.__init__

    def guarded_init(self, family=socket.AF_INET, *args, **kwargs):
        if family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError(
                "Network access attempted during smoke run; "
                "scanner must stay fully fixture-driven."
            )
        return real_socket_init(self, family, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "__init__", guarded_init)


def test_agol_scan_opens_no_real_sockets(
    block_real_sockets,
    mocked_routes,
    tmp_output_dir: Path,
) -> None:
    output = tmp_output_dir / "EsriFootprint.json"
    with mocked_routes("agol/happy"):
        exit_code = cli_main(
            [
                "scan",
                "agol",
                "--target",
                "https://fixture.local/sharing/rest",
                "--output",
                str(output),
            ]
        )
    assert exit_code == 0
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert footprint["source"]["kind"] == "arcgis-online"
    assert footprint["inventory"], "expected inventory to be populated under the no-network guard"


def test_filegdb_scan_opens_no_real_sockets(
    block_real_sockets,
    tmp_output_dir: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "filegdb" / "happy" / "sample.gdb"
    output = tmp_output_dir / "EsriFootprint.json"
    exit_code = cli_main(
        [
            "scan",
            "filegdb",
            "--target",
            str(fixture),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    footprint = json.loads(output.read_text(encoding="utf-8"))
    assert footprint["source"]["kind"] == "filegdb"
