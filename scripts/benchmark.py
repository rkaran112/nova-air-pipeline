"""Measure the pipeline on the small and medium profiles and write docs/BENCHMARKS.md.

    python -m scripts.benchmark                      # small and medium (medium takes a while)
    python -m scripts.benchmark --profiles small

Each profile gets its own folder under data/bench/, so your main data/ is untouched.
Every number written comes from this run: nothing is typed in by hand.
"""

import argparse
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import psutil

REPO = Path(__file__).resolve().parent.parent
FIRST_DAY, LAST_DAY = "2025-07-01", "2025-12-31"
STEPS = ("ingest_bronze", "load_silver", "build_gold", "check_gold", "export")
TABLES = ("bronze.flights", "bronze.bookings", "bronze.passengers", "silver.flights",
          "silver.bookings", "silver.passengers", "silver.quarantine", "gold.fact_flight",
          "gold.fact_booking", "gold.mart_booking_daily")


def run_measured(command):
    """Run a command; return (seconds, peak memory in MB, exit code).

    Memory is the resident memory of the process and its children, sampled every
    0.2 s, so a very short spike between samples can be missed.
    """
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=REPO, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    watched = psutil.Process(process.pid)
    peak = 0
    while process.poll() is None:
        try:
            family = [watched] + watched.children(recursive=True)
            peak = max(peak, sum(p.memory_info().rss for p in family))
        except psutil.Error:
            pass
        time.sleep(0.2)
    return round(time.perf_counter() - started, 1), round(peak / 2**20), process.returncode


def row_counts(warehouse):
    with duckdb.connect(str(warehouse), read_only=True) as con:
        counts = {table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in TABLES}
        steps = dict(con.execute("""
            SELECT step, round(sum(duration_seconds), 1) FROM meta.pipeline_runs
            WHERE run_id = (SELECT min(run_id) FROM meta.pipeline_runs) GROUP BY step
        """).fetchall())
    return counts, steps


def benchmark(profile, bench_root):
    data_dir = bench_root / profile
    if data_dir.exists():
        shutil.rmtree(data_dir)
    python = sys.executable
    result = {"profile": profile}
    print(f"[{profile}] generating data...", flush=True)
    result["generate"] = run_measured([python, "-m", "scripts.generate_data", "--profile",
                                       profile, "--data-dir", str(data_dir)])
    print(f"[{profile}] backfilling {FIRST_DAY}..{LAST_DAY}...", flush=True)
    result["backfill"] = run_measured([python, "-m", "pipeline.run", "--start", FIRST_DAY,
                                       "--end", LAST_DAY, "--data-dir", str(data_dir)])
    print(f"[{profile}] re-running the last day...", flush=True)
    result["rerun"] = run_measured([python, "-m", "pipeline.run", "--date", LAST_DAY,
                                    "--data-dir", str(data_dir)])
    warehouse = data_dir / "warehouse" / "nova.duckdb"
    result["counts"], result["steps"] = row_counts(warehouse)
    result["landing_mb"] = round(sum(p.stat().st_size for p in
                                     (data_dir / "landing").rglob("*") if p.is_file()) / 2**20)
    result["warehouse_mb"] = round(warehouse.stat().st_size / 2**20)
    return result


def disk_kind(path):
    """Best effort: is the benchmark folder on an SSD or a spinning hard disk?"""
    if platform.system() != "Windows":
        return "unknown"
    drive = path.resolve().drive.rstrip(":")
    script = (f"(Get-Partition -DriveLetter {drive} | Get-Disk | Get-PhysicalDisk)"
              ".MediaType")
    try:
        output = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                capture_output=True, text=True, timeout=30).stdout
        return output.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def markdown(results, bench_root):
    lines = [
        "# Benchmarks",
        "",
        f"Measured by `python -m scripts.benchmark` on {datetime.now():%d %b %Y}. "
        "Every number below was written by that script; none were typed in.",
        "",
        "## Machine",
        "",
        f"- {platform.system()} {platform.version()}, Python {platform.python_version()}, "
        f"DuckDB {duckdb.__version__}",
        f"- {psutil.cpu_count(logical=True)} logical CPUs, "
        f"{round(psutil.virtual_memory().total / 2**30, 1)} GB RAM",
        f"- Data folder `{bench_root}` is on a disk reported as: **{disk_kind(bench_root)}**",
        "",
        "## Timings",
        "",
        "Wall-clock seconds, including Python start-up. Peak memory is the resident memory "
        "of the process and its children, sampled every 0.2 s.",
        "",
        "| Profile | Generate (s) | Backfill 184 days (s) | Peak memory, backfill (MB) | "
        "Re-run one day (s) | Landing files (MB) | Warehouse file (MB) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['profile']} | {r['generate'][0]} | {r['backfill'][0]} | "
                     f"{r['backfill'][1]} | {r['rerun'][0]} | {r['landing_mb']} | "
                     f"{r['warehouse_mb']} |")
    lines += ["", "Time inside each step during the backfill (seconds, from "
              "`meta.pipeline_runs`; the rest of the wall time is Python start-up, "
              "commits and the final checkpoint):", "",
              "| Profile | " + " | ".join(STEPS) + " |",
              "|---|" + "---|" * len(STEPS)]
    for r in results:
        lines.append(f"| {r['profile']} | "
                     + " | ".join(str(r["steps"].get(step, "")) for step in STEPS) + " |")
    lines += ["", "## Rows", "", "| Table | " + " | ".join(r["profile"] for r in results) + " |",
              "|---|" + "---|" * len(results)]
    for table in TABLES:
        lines.append(f"| {table} | " + " | ".join(f"{r['counts'][table]:,}" for r in results)
                     + " |")
    exit_codes = {r["profile"]: (r["generate"][2], r["backfill"][2], r["rerun"][2])
                  for r in results}
    lines += ["", f"Exit codes (generate, backfill, re-run): {exit_codes}", "",
              "## Reading these numbers", "",
              "- Wall time minus the step times is Python start-up, commits (two per day) "
              "and the final checkpoint.",
              "- Re-running one day is not \"one day of work\": it also rebuilds all of gold, "
              "re-checks it and re-exports it, which is why it grows with the total data.",
              "- Peak memory stays far below the data size because DuckDB streams through "
              "files instead of loading them whole.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profiles", nargs="+", default=["small", "medium"])
    parser.add_argument("--bench-root", type=Path, default=REPO / "data" / "bench")
    parser.add_argument("--output", type=Path, default=REPO / "docs" / "BENCHMARKS.md")
    args = parser.parse_args(argv)
    results = [benchmark(profile, args.bench_root) for profile in args.profiles]
    args.output.write_text(markdown(results, args.bench_root), encoding="utf-8")
    print(f"wrote {args.output}")
    failed = [r["profile"] for r in results
              if any(step[2] != 0 for step in (r["generate"], r["backfill"], r["rerun"]))]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
