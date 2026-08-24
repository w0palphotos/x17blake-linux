import struct
import sys


def parse_pcap(path):
    data = open(path, "rb").read()
    if len(data) < 24:
        return []
    magic = data[:4]
    if magic == b"\x0a\x0d\x0d\x0a":
        return _parse_pcapng(data)
    if magic in (b"\xa1\xb2\xc3\xd4", b"\xd4\xc3\xb2\xa1"):
        return _parse_pcap_classic(data, magic)
    raise ValueError(f"unknown capture magic {magic.hex()}")


def _parse_pcap_classic(data, magic):
    swapped = magic == b"\xa1\xb2\xc3\xd4"
    packets = []
    off = 24
    fmt = ">IIII" if swapped else "<IIII"
    while off + 16 <= len(data):
        _, _, incl, _orig = struct.unpack_from(fmt, data, off)
        off += 16
        if incl > len(data) - off:
            break
        packets.append(data[off : off + incl])
        off += incl
    return packets


def _parse_pcapng(data):
    packets = []
    off = 0
    while off + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, off)
        if blen < 12 or off + blen > len(data):
            break
        if btype == 6:
            caplen, origlen = struct.unpack_from("<II", data, off + 20)
            packets.append(data[off + 28 : off + 28 + caplen])
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
    for pkt in parse_pcap(path):
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
