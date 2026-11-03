"""The generator is reproducible, and its defects can be switched off."""

import json

from scripts.generate_data import main


def read_tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*")
            if p.is_file()}


def test_same_seed_gives_identical_files(tmp_path):
    for name in ("a", "b"):
        main(["--data-dir", str(tmp_path / name), "--end", "2025-07-02"])
    assert read_tree(tmp_path / "a" / "landing") == read_tree(tmp_path / "b" / "landing")


def test_no_defects_flag_plants_nothing(tmp_path):
    main(["--data-dir", str(tmp_path), "--end", "2025-07-02", "--no-defects"])
    counts = json.loads((tmp_path / "generator_manifest.json").read_text())["counts"]
    planted = {k: v for k, v in counts.items()
               if k.startswith(("flight_", "booking_", "passenger_"))
               and k != "flight_overnight_time_only_arrival" and v}
    assert planted == {}
