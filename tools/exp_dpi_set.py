import sys

sys.path.insert(0, ".")

from x17blake import hidraw, protocol


def tx(port, frame, label):
    port.write_output_report(frame)
    resp = port.read_input_report(timeout=1.0)
    print(f"--- {label} ---")
    if resp is None:
        print("no response")
        return None
    print(protocol.format_hexdump(resp))
    return resp


def drain(port):
    while True:
        pkt = port.read_input_report(timeout=0.2)
        if pkt is None:
            break
        print("drained:", pkt.hex())


def stage1_of(frame):
    return (protocol.dpi_from_register(frame[10]), protocol.dpi_from_register(frame[11]))


def main():
    port = hidraw.open_config_interface(interface=1)
    with port:
        get = protocol.build_get_settings()

        before = tx(port, get, "GET before")
        assert before is not None
        print("stage1 before:", stage1_of(before))

        mutated = bytearray(before)
        reg = protocol.dpi_to_register(800)
        mutated[10] = reg
        mutated[11] = reg
        mutated[3] = protocol.CMD_SET_SETTINGS
        ack = tx(port, bytes(mutated), "SET stage1=800")
        assert ack is not None

        import time

        time.sleep(0.2)
        drain(port)

        after = tx(port, get, "GET after set")
        print("stage1 after:", stage1_of(after))

        restored = bytearray(after)
        restored[10] = before[10]
        restored[11] = before[11]
        restored[3] = protocol.CMD_SET_SETTINGS
        tx(port, bytes(restored), "SET restore")
        time.sleep(0.2)
        drain(port)

        final = tx(port, get, "GET after restore")
        print("stage1 final:", stage1_of(final))
        print()
        print("VERDICT:",
              "SET APPLIES" if stage1_of(after)[0] == 800 else "SET NOT APPLIED",
              "|",
              "RESTORE OK" if stage1_of(final) == stage1_of(before) else "RESTORE FAILED")


if __name__ == "__main__":
    main()
