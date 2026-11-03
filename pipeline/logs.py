"""Structured logging: every line is `event=... key=value ...`, easy to read and to grep.

Each step's result is also written to meta.pipeline_runs, which is the lasting record
the dashboard reads. The log lines are for whoever is watching the run.
"""

import logging
import sys

LOGGER = logging.getLogger("nova")


def configure_logging(level=logging.INFO):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s level=%(levelname)s %(message)s",
                                           datefmt="%H:%M:%S"))
    LOGGER.handlers[:] = [handler]
    LOGGER.setLevel(level)


def format_fields(fields):
    parts = []
    for key, value in fields.items():
        text = str(value)
        if " " in text or text == "":
            text = '"' + text.replace('"', "'") + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_event(event, level=logging.INFO, **fields):
    LOGGER.log(level, "event=%s %s", event, format_fields(fields))


def record_step(con, run_id, step, target, status, started_at, seconds, counts, message=""):
    con.execute(
        """INSERT INTO meta.pipeline_runs VALUES ($run_id, $step, $target, $status, $started_at,
           $seconds, $rows_in, $rows_out, $rows_quarantined, $message)""",
        {"run_id": run_id, "step": step, "target": target, "status": status,
         "started_at": started_at, "seconds": round(seconds, 3),
         "rows_in": counts.get("rows_in", 0), "rows_out": counts.get("rows_out", 0),
         "rows_quarantined": counts.get("rows_quarantined", 0), "message": message})
