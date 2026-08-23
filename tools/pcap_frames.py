import struct
import sys


def parse_pcapng_usb(path):
    data = open(path, "rb").read()
    packets = []
    off = 0
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if blen < 12 or off + blen > len(data):
            break
        if btype == 6:
            ifid, ts_hi, ts_lo = struct.unpack_from("<III", data, off + 8)
            caplen, origlen = struct.unpack_from("<II", data, off + 20)
            pkt = data[off + 28 : off + 28 + caplen]
            packets.append(pkt)
        off += blen
    return packets


USB_HEADER = 64


def usb_payload(pkt):
    if len(pkt) <= USB_HEADER:
        return None
    flags = struct.unpack_from("<H", pkt, 8)[0]
    direction = (flags >> 15) & 1
    ep_num = (flags >> 7) & 0x7F
    xfer_type = flags & 0x3
    payload = bytes(pkt[USB_HEADER:])
    return direction, ep_num, xfer_type, payload


def frames(path):
    out = []
    for pkt in parse_pcapng_usb(path):
        parsed = usb_payload(pkt)
        if not parsed:
            continue
        direction, ep, xfer, payload = parsed
        if payload and payload[0] == 0x04:
            tag = "OUT" if direction == 0 else "IN"
            out.append((tag, ep, bytes(payload)))
    return out


for path in sys.argv[1:]:
    print(f"== {path} ==")
    seen = []
    for tag, ep, payload in frames(path):
        line = f"{tag} {payload.hex()}"
        if line in seen:
            continue
        seen.append(line)
        print(f"  [{tag} ep{ep}] {payload.hex()}")
    print()
