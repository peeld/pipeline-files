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


def test_query(capsys, tmp_path):
    config = tmp_path / "layout.yaml"
    config.write_text(
        "version: 1\n"
        "keys: {shot: {type: int, pad: 3}, version: {type: int, format: 'v{value}', pad: 3},"
        " frame: {type: int, pad: 4}}\n"
        f"roots: {{shots: '{(tmp_path / 'shots').as_posix()}'}}\n"
        "rules:\n"
        "  render: {root: shots, keys: [shot, version], templates: {fs: '{shot}/{version}'}}\n"
        "  frame: {parent: render, keys: [frame], templates: {fs: 'img.{frame}.exr'}}\n"
    )
    for version, frames in ((1, (1, 2)), (2, (1, 2, 3, 5))):
        (tmp_path / "shots" / "010" / f"v{version:03d}").mkdir(parents=True)
        for frame in frames:
            (tmp_path / "shots" / "010" / f"v{version:03d}" / f"img.{frame:04d}.exr").write_text("")

    assert main([str(config), "query", "render", "shot=10"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["location"] for line in lines] == ["fs://shots/010/v001", "fs://shots/010/v002"]

    assert main([str(config), "query", "frame", "--newest", "version", "--collapse", "frame"]) == 0
    [line] = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert line == {"rule": "frame", "fields": {"shot": 10, "version": 2}, "frame": "1-3,5"}

    assert main([str(config), "query", "frame", "version=1", "--path"]) == 0
    assert capsys.readouterr().out.count("img.000") == 2
