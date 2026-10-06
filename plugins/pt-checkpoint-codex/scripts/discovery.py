"""Validated, locked, append-only discovery ledger CLI."""
import argparse
from collections import Counter
from datetime import datetime
import fcntl
import json
import os
import re
import sys
from common import checked_path, initialize, project_root, timestamp

STATUS = ("confirmed", "hypothesis", "tested", "negative-result", "blocked", "skipped", "superseded")
TYPES = ("endpoint", "parameter", "authentication", "authorization", "header", "cookie", "technology", "observation", "test", "finding-candidate", "negative-result", "evidence", "scope", "other")
CONFIDENCE = ("confirmed", "high", "medium", "low", "unknown")
FIELDS = ("id", "timestamp", "type", "status", "target", "value", "summary", "evidence", "confidence", "source", "metadata")


def validate_record(record: dict) -> None:
    if not isinstance(record, dict) or set(record) != set(FIELDS):
        raise ValueError("record must contain exactly the schema fields")
    for key in ("id", "timestamp", "type", "status", "summary", "confidence", "source"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(key + " must be a nonempty string")
    for key in ("target", "value"):
        if not isinstance(record[key], str):
            raise ValueError(key + " must be a string")
    if not re.fullmatch(r"[DTB]-[0-9]{6,}", record["id"]):
        raise ValueError("invalid record id")
    if record["type"] not in TYPES or record["status"] not in STATUS or record["confidence"] not in CONFIDENCE:
        raise ValueError("invalid type, status, or confidence")
    if not isinstance(record["evidence"], list) or any(not isinstance(x, str) or not x.strip() for x in record["evidence"]):
        raise ValueError("evidence must be an array of nonempty paths")
    if not isinstance(record["metadata"], dict):
        raise ValueError("metadata must be an object")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["timestamp"]):
        raise ValueError("timestamp must be UTC YYYY-MM-DDTHH:MM:SSZ")
    datetime.strptime(record["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
    json.dumps(record, allow_nan=False)


def read_records(stream) -> list:
    records, ids = [], set()
    for number, line in enumerate(stream, 1):
        try:
            record = json.loads(line)
            validate_record(record)
            if record["id"] in ids:
                raise ValueError("duplicate record id")
            ids.add(record["id"])
            records.append(record)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    return records


def append_record(root, record) -> dict:
    initialize(root)
    path = checked_path(root, "discoveries.jsonl")
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
    with os.fdopen(fd, "a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        records = read_records(stream)
        record = dict(record, id="D-%06d" % (1 + max((int(x["id"].split("-")[1]) for x in records), default=0)), timestamp=timestamp())
        validate_record(record)
        stream.seek(0, os.SEEK_END)
        # Preserve a valid final record even when its trailing newline is missing.
        if stream.tell():
            with path.open("rb") as binary:
                binary.seek(-1, os.SEEK_END)
                if binary.read(1) != b"\n":
                    stream.write("\n")
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="project directory (default: working directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--type", required=True, choices=TYPES)
    add.add_argument("--status", required=True, choices=STATUS)
    add.add_argument("--summary", required=True)
    add.add_argument("--target", default="")
    add.add_argument("--value", default="")
    add.add_argument("--evidence", action="append", default=[])
    add.add_argument("--confidence", choices=CONFIDENCE, default="unknown")
    add.add_argument("--source", default="manual")
    add.add_argument("--metadata", default="{}", help="JSON object")
    commands.add_parser("validate")
    tail = commands.add_parser("tail")
    tail.add_argument("--count", type=int, default=20)
    commands.add_parser("stats")
    args = parser.parse_args()
    try:
        root = project_root(explicit=args.project)
        if args.command == "add":
            record = {key: getattr(args, key) for key in FIELDS if key not in ("id", "timestamp")}
            record["metadata"] = json.loads(args.metadata)
            print(json.dumps(append_record(root, record), ensure_ascii=False))
        else:
            with checked_path(root, "discoveries.jsonl").open(encoding="utf-8") as stream:
                fcntl.flock(stream, fcntl.LOCK_SH)
                records = read_records(stream)
            if args.command == "validate":
                print(f"Valid: {len(records)} records")
            elif args.command == "stats":
                print(json.dumps({"total": len(records), "type": dict(Counter(x["type"] for x in records)), "status": dict(Counter(x["status"] for x in records))}))
            else:
                if args.count < 0:
                    raise ValueError("count must be nonnegative")
                for record in records[-args.count:] if args.count else []:
                    print(json.dumps(record, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"pt-checkpoint: {exc}\n")


if __name__ == "__main__":
    main()
