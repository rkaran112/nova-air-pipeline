"""Write source records to landing files, dropping the hidden "_" keys."""

import csv
import json


def visible(record):
    return {key: value for key, value in record.items() if not key.startswith("_")}


def write_json(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump([visible(r) for r in records], file, indent=2)


def write_csv(path, records, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(visible(record))
