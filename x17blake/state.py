import json
import os
import time

from . import protocol


STATE_DIR = os.path.expanduser("~/.config/x17blake")
LATEST = os.path.join(STATE_DIR, "latest.json")


class SafetyError(Exception):
    pass


def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def save_backup(frame, label="manual"):
    _ensure_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "frame_hex": bytes(frame).hex(),
    }
    path = os.path.join(STATE_DIR, f"backup-{ts}-{label}.json")
    for target in (path, LATEST):
        with open(target, "w") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
    return LATEST


def load_backup(path):
    with open(path) as fh:
        record = json.load(fh)
    frame = bytes.fromhex(record["frame_hex"])
    if len(frame) != protocol.REPORT_SIZE:
        raise SafetyError(f"backup {path} holds {len(frame)} bytes, expected {protocol.REPORT_SIZE}")
    return frame, record


def latest_path():
    return LATEST if os.path.exists(LATEST) else None


def diff_bytes(before, after):
    return [i for i in range(min(len(before), len(after))) if before[i] != after[i]]


HEADER_OFFSETS = frozenset(range(0, 4))
MUTABLE_OFFSETS = frozenset([7, *range(9, 30), 33])
FORBIDDEN_NOTE = (
    "LED/profile fields (37-41, 42-62) are write-blocked: on this firmware "
    "they are NOT the lighting store; writing them corrupts the LED engine "
    "until factory reset. True lighting opcodes not yet decoded."
)


def validate_mutations(before, after):
    changed = [
        i for i in diff_bytes(before, after) if i not in HEADER_OFFSETS
    ]
    bad = [i for i in changed if i not in MUTABLE_OFFSETS]
    if bad:
        pretty = ", ".join(f"{i} ({before[i]:#04x}->{after[i]:#04x})" for i in bad)
        raise SafetyError(
            "refusing to write unverified fields: " + pretty
        )
    return changed
