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
    """Decode a usbmon mmapped record (tcpdump classic pcap).

    Header layout (Documentation/usb/usbmon.txt):
      [0:8]  urb id
      [8]    event type b'S'/b'C'/b'E'
      [9]    transfer type (0 iso, 1 intr, 2 control, 3 bulk)
      [10]   endpoint | 0x80 when IN
      [11]   device address
      [12:15] bus number
      [64:]  data
    """
    if len(pkt) <= 64:
        return None
    event = pkt[8]
    if event != ord("S"):
        return None
    xfer_type = pkt[9]
    ep_byte = pkt[10]
    direction = 1 if ep_byte & 0x80 else 0
    ep_num = ep_byte & 0x7F
    payload = bytes(pkt[64:])
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
