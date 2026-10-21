from __future__ import annotations

import json
from pathlib import Path

from entitylayout.cli import main

from conftest import FIXTURES

VFX = str(FIXTURES / "vfx")


def test_locate_and_parse(capsys):
    args = ["project=alpha", "sequence=ABC", "shot=40", "version=3", "camera=main"]
    assert main([VFX, "locate", "media", *args]) == 0
    uri = capsys.readouterr().out.strip()
    assert uri == "fs://projects/alpha/shots/ABC/ABC_040/media/v003/main"

    assert main([VFX, "parse", uri]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "rule": "media",
        "fields": {"project": "alpha", "sequence": "ABC", "shot": 40, "version": 3, "camera": "main"},
    }


def test_locate_real_path_and_parse_it_back(capsys):
    args = ["project=alpha", "sequence=ABC", "shot=40"]
    assert main([VFX, "locate", "shot", *args, "--path"]) == 0
    path = capsys.readouterr().out.strip()
    assert Path(path).parts[-4:] == ("alpha", "shots", "ABC", "ABC_040")
    assert main([VFX, "parse", path]) == 0
    assert json.loads(capsys.readouterr().out)["rule"] == "shot"


def test_dates_print_as_iso(capsys):
    lab = str(FIXTURES / "lab")
    assert main([lab, "parse", "fs://raw/ABC12/S017/session2/instrument_B/20261021_007"]) == 0
    assert json.loads(capsys.readouterr().out)["fields"]["date"] == "2026-10-21"


def test_errors_exit_nonzero(capsys):
    assert main([VFX, "locate", "media", "project=alpha"]) == 1
    assert "missing key" in capsys.readouterr().err
    assert main([VFX, "locate", "media", "colour=red"]) == 1
    assert "no key 'colour'" in capsys.readouterr().err
    assert main([VFX, "locate", "media", "project"]) == 1
    assert "key=value" in capsys.readouterr().err
    assert main([VFX, "parse", "fs://projects/nothing"]) == 1


def test_check(capsys, tmp_path):
    config = tmp_path / "layout.yaml"
    config.write_text(f"version: 1\nroots:\n  here: {tmp_path}\n")
    assert main([str(config), "check"]) == 0
    assert capsys.readouterr().out.startswith("ok:")
    config.write_text(f"version: 1\nroots:\n  gone: {tmp_path / 'gone'}\n")
    assert main([str(config), "check"]) == 1
