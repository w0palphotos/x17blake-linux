import time

from . import hidraw, protocol
from .state import (
    SafetyError,
    binding_table,
    load_binding_entries,
    validate_mutations,
)


class DeviceError(Exception):
    pass


class Device:
    def __init__(self, interface=1):
        self._port = hidraw.open_config_interface(interface=interface)
        # The commit frame defines the WHOLE binding table (absent slot
        # = unbound), so feature writes must always carry the tracked
        # bindings or they would silently wipe them.
        self._tracked_bindings = load_binding_entries()

    def __enter__(self):
        self._port.open()
        return self

    def __exit__(self, *exc):
        self._port.close()

    def reload_bindings(self):
        """Re-read the tracked table after keys bind/clear changed it."""
        self._tracked_bindings = load_binding_entries()

    def binding_commit(self):
        """Commit frame that preserves all tracked button bindings."""
        return protocol.build_commit(binding_table(self._tracked_bindings))

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
        self._port.exchange(
            commit if commit is not None else self.binding_commit()
        )
        time.sleep(0.05)
        return self.read()


    def upload_macro(self, macro_id, steps):
        """Upload a macro to the mouse (OemDrv apply sequence, RE'd 2026-08-30).

        steps: list of ("down", hid) | ("up", hid) | ("delay", ms)
        Sequence: FreeMacroID(0) `AA 00` -> A7 header (acked) -> A8 chunks.
        Timing mirrors OemDrv: 100ms after opener, 50ms after A7, 15ms
        between chunks, 50ms tail (before the binding commit).
        """
        frames = protocol.build_macro_frames(macro_id, steps)
        a7, chunks = frames[0], frames[1:]
        self._port.exchange(protocol.build_macro_opener())
        time.sleep(0.1)
        resp = self._port.exchange(a7)
        acked = any(len(p) > 2 and p[0] == protocol.REPORT_ID
                    and p[1] == 0xA7 and p[2] == 1 for p in resp)
        if not acked:
            raise DeviceError(
                f"macro header (A7) not accepted by device: "
                + "; ".join(p.hex() for p in resp[:3])
            )
        time.sleep(0.05)
        for frame in chunks:
            self._port.exchange(frame)
            time.sleep(0.015)
        time.sleep(0.05)

    def led_begin_session(self):
        for _ in range(2):
            for step in range(4):
                self._port.exchange(protocol.build_init_step(step))
