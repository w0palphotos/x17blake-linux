import time

from . import hidraw, protocol
from .state import SafetyError, validate_mutations


class DeviceError(Exception):
    pass


class Device:
    def __init__(self, interface=1):
        self._port = hidraw.open_config_interface(interface=interface)

    def __enter__(self):
        self._port.open()
        return self

    def __exit__(self, *exc):
        self._port.close()

    def read(self):
        pkt = protocol.settings_from_packets(
            self._port.exchange(protocol.build_get_settings())
        )
        if pkt is None:
            raise DeviceError("no response to GET; is the mouse connected?")
        return pkt

    def apply(self, frame, validate=True, commit=None):
        out = bytearray(frame)
        out[3] = protocol.CMD_SET_SETTINGS
        if validate:
            current = self.read()
            validate_mutations(current, out)
        self._port.exchange(bytes(out))
        self._port.exchange(commit if commit is not None else protocol.build_commit())
        time.sleep(0.05)
        return self.read()

    def led_begin_session(self):
        for _ in range(2):
            for step in range(4):
                self._port.exchange(protocol.build_init_step(step))
