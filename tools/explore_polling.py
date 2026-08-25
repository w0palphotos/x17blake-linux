#!/usr/bin/env python3
"""VM-free polling-rate explorer for X17 Blake (2ea8:2203).

Writes 2-byte candidate frames observed as 0101/0103 on EP3 OUT (int)
and checks whether bInterval changes or the device re-enumerates.

Usage:
  python3 tools/explore_polling.py --single 0101
  python3 tools/explore_polling.py --sweep 0101 0102 0103 0104
  python3 tools/explore_polling.py --sweep-all   # 0100..010F

Every write auto-handles re-enumeration (Link) and prints bInterval
before/after plus lsusb -v bInterval + descriptor bytes.
"""
import argparse, glob, os, sys, time, subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from x17blake import hidraw  # noqa: E402

def find_usb_path():
    for p in glob.glob("/sys/bus/usb/devices/*"):
        try:
            if open(os.path.join(p, "idVendor")).read().strip() == "2ea8" and open(os.path.join(p, "idProduct")).read().strip() == "2203":
                return p
        except OSError:
            continue
    return None

def read_bintervals():
    path = find_usb_path()
    if not path:
        return {}
    out = {}
    for ep in ["3-2:1.0/ep_81/bInterval", "3-2:1.1/ep_82/bInterval", "3-2:1.1/ep_03/bInterval"]:
        # use discovered path's basename
        base = os.path.basename(path)
        for cand in glob.glob(f"/sys/bus/usb/devices/{base}*"):
            pass
        # brute: find all bInterval under path
    # generic walk
    res = {}
    if path:
        for root, dirs, files in os.walk(path):
            if "bInterval" in files:
                try:
                    v = open(os.path.join(root, "bInterval")).read().strip()
                    res[os.path.join(root, "bInterval")] = v
                except OSError:
                    pass
    return res

def read_descriptor_bintervals():
    try:
        out = subprocess.check_output(["lsusb", "-v", "-d", "2ea8:2203"], text=True, stderr=subprocess.DEVNULL)
        intervals = []
        for line in out.splitlines():
            if "bInterval" in line:
                intervals.append(line.strip())
        return intervals
    except Exception:
        return []

class Link:
    def __init__(self):
        self.port = None
    def _reopen(self):
        try:
            if self.port:
                self.port.close()
        except OSError:
            pass
        self.port = None
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                self.port = hidraw.open_config_interface(interface=1)
                self.port.open()
                return True
            except FileNotFoundError:
                time.sleep(0.7)
        raise SystemExit("device did not come back within 15s")
    def open(self):
        self._reopen()
    def close(self):
        if self.port:
            try: self.port.close()
            except OSError: pass
    def write_short(self, hx):
        data = bytes.fromhex(hx)
        try:
            self.port.write_output_report(data)
            return True, None
        except OSError as e:
            return False, str(e)

def probe_one(hexstr, dwell=2.0):
    link = Link()
    link.open()
    before_path = find_usb_path()
    before_intervals = read_bintervals()
    before_lsusb = read_descriptor_bintervals()
    print(f"\n=== {hexstr} ===", flush=True)
    print(f"before intervals: {before_intervals}", flush=True)
    ok, err = link.write_short(hexstr)
    print(f"write {hexstr}: {'ok' if ok else 'err '+str(err)}", flush=True)
    time.sleep(dwell)
    # check if link still alive, else reopen
    after_path = find_usb_path()
    reenum = (before_path != after_path)
    if reenum:
        print(f"re-enumerated: {before_path} -> {after_path}", flush=True)
        # reopen link
        try:
            link._reopen()
        except SystemExit as e:
            print(str(e), flush=True)
    after_intervals = read_bintervals()
    after_lsusb = read_descriptor_bintervals()
    print(f"after intervals: {after_intervals}", flush=True)
    if after_lsusb != before_lsusb:
        print("lsusb bInterval change:", after_lsusb, flush=True)
    else:
        print("lsusb intervals unchanged", flush=True)
    link.close()
    return {"hex": hexstr, "before": before_intervals, "after": after_intervals, "reenum": reenum}

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--single", metavar="HEX")
    g.add_argument("--sweep", nargs="+", metavar="HEX")
    g.add_argument("--sweep-all", action="store_true")
    ap.add_argument("--dwell", type=float, default=2.0)
    args = ap.parse_args()
    if args.sweep_all:
        lst = [f"010{i:x}" for i in range(0x10)]  # 0100..010f
    elif args.sweep:
        lst = args.sweep
    else:
        lst = [args.single]
    for hx in lst:
        # normalize
        hx = hx.lower().replace(" ", "")
        if len(hx) % 2: hx = "0"+hx
        probe_one(hx, dwell=args.dwell)
        time.sleep(1.0)

if __name__ == "__main__":
    main()
