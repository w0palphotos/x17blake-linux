import fcntl
import glob
import os
import select


VENDOR_ID = 0x2EA8
PRODUCT_ID = 0x2203

_HID_TYPE = 0x48
_IOC_WRITE_READ = 0b11


def _ioctl_nr(size, nr):
    return (_IOC_WRITE_READ << 30) | (size << 16) | (_HID_TYPE << 8) | nr


def _hidocsfeature(size):
    return _ioctl_nr(size, 0x06)


def _hidiocgfeature(size):
    return _ioctl_nr(size, 0x07)


def find_hidraw(interface=None):
    matches = []
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(path, "device", "uevent")) as fh:
                uevent = fh.read()
        except OSError:
            continue
        if f"0003:{VENDOR_ID:08X}:{PRODUCT_ID:08X}" not in uevent:
            continue
        try:
            with open(os.path.join(path, "device", "..", "bInterfaceNumber")) as fh:
                iface = int(fh.read().strip())
        except (OSError, ValueError):
            iface = None
        if interface is None or iface == interface:
            matches.append((iface, "/dev/" + os.path.basename(path)))
    return matches


class ConfigPort:
    def __init__(self, path):
        self.path = path
        self._fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    def open(self):
        self._fd = os.open(self.path, os.O_RDWR)

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def send_feature_report(self, data):
        buf = bytes(data)
        return fcntl.ioctl(self._fd, _hidocsfeature(len(buf)), buf, True)

    def get_feature_report(self, report_id, size=64):
        buf = bytearray(size)
        buf[0] = report_id
        count = fcntl.ioctl(self._fd, _hidiocgfeature(size), buf, True)
        return bytes(buf[: int(count)])

    def write_output_report(self, data):
        return os.write(self._fd, bytes(data))

    def read_input_report(self, size=64, timeout=1.0):
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return None
        return os.read(self._fd, size)

    def exchange(self, frame, quiet_window=0.25):
        self.write_output_report(frame)
        packets = []
        while True:
            pkt = self.read_input_report(timeout=quiet_window)
            if pkt is None:
                break
            packets.append(pkt)
            if len(packets) >= 8:
                break
        return packets


def open_config_interface(interface=1):
    for iface, devnode in find_hidraw(interface=interface):
        port = ConfigPort(devnode)
        port.iface = iface
        return port
    raise FileNotFoundError(
        f"no hidraw node for {VENDOR_ID:04x}:{PRODUCT_ID:04x} "
        f"(interface={interface}); check udev rules and permissions"
    )
