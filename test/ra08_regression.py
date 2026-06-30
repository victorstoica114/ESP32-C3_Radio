import sys
import time

import serial


PORTS = ("COM20", "COM21")
BAUD = 115200


def normalize(text):
    return text.replace("\r", "\\r").replace("\n", "\\n\n")


def read_all(ser, settle=0.15, quiet=0.12, total=0.8):
    time.sleep(settle)
    data = bytearray()
    deadline = time.time() + total
    quiet_deadline = time.time() + quiet

    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            data.extend(ser.read(waiting))
            quiet_deadline = time.time() + quiet
        elif time.time() >= quiet_deadline:
            break
        else:
            time.sleep(0.02)

    return bytes(data).decode(errors="replace")


def send_cmd(ser, text, wait=0.18):
    ser.reset_input_buffer()
    ser.write((text + "\r\n").encode())
    ser.flush()
    return read_all(ser, wait)


def expect(label, out, *needles):
    print(f"--- {label} ---")
    print(normalize(out))
    missing = [needle for needle in needles if needle not in out]
    if missing:
        raise RuntimeError(f"{label}: missing {missing}")


def open_port(port):
    ser = serial.Serial(port, BAUD, timeout=0.2)
    boot = read_all(ser, 0.4)
    if boot:
        print(f"--- {port} boot ---")
        print(normalize(boot))
    return ser


def restore_working_config(ser, port):
    commands = (
        "AT+FREQ=433000000",
        "AT+CHAN=0",
        "AT+PWR=2",
        "AT+SF=7",
        "AT+BW=125000",
        "AT+CR=4/5",
        "AT+RX=OFF",
    )
    for command in commands:
        expect(f"{port} restore {command}", send_cmd(ser, command, 0.22), "OK")
    expect(
        f"{port} restored cfg",
        send_cmd(ser, "AT+CFG?"),
        "FREQ=433000000",
        "CHAN=0",
        "PWR=2",
        "SF=7",
        "BW=125000",
        "CR=4/5",
        "RX=OFF",
        "SLEEP=0",
        "OK",
    )


def run_basic_tests(port):
    with open_port(port) as ser:
        expect(f"{port} AT", send_cmd(ser, "AT"), "OK")
        expect(f"{port} AT?", send_cmd(ser, "AT?", 0.35), "RA08 AT commands", "AT?", "AT+?", "OK")
        expect(f"{port} AT+?", send_cmd(ser, "AT+?", 0.35), "RA08 AT commands", "AT?", "AT+?", "OK")
        expect(
            f"{port} AT+HELP",
            send_cmd(ser, "AT+HELP", 0.35),
            "AT+VERSION?",
            "AT+STATUS?",
            "AT+LASTPKT?",
            "+RX:<rssi>,<snr>,<len>,<hex>",
            "OK",
        )
        expect(f"{port} AT+VERSION?", send_cmd(ser, "AT+VERSION?"), "+VERSION:0.1.3", "OK")
        expect(f"{port} AT+CFG?", send_cmd(ser, "AT+CFG?"), "+CFG:", "FREQ=433000000", "MAXPL=255", "OK")

        queries = (
            ("AT+FREQ?", "+FREQ:"),
            ("AT+CHAN?", "+CHAN:"),
            ("AT+PWR?", "+PWR:"),
            ("AT+SF?", "+SF:"),
            ("AT+BW?", "+BW:"),
            ("AT+CR?", "+CR:"),
            ("AT+RX?", "+RX:"),
            ("AT+SLEEP?", "+SLEEP:"),
            ("AT+STATUS?", "+STATUS:"),
            ("AT+LASTPKT?", "+LASTPKT:"),
        )
        for command, token in queries:
            expect(f"{port} {command}", send_cmd(ser, command), token, "OK")

        expect(f"{port} invalid command", send_cmd(ser, "AT+NOPE"), "#ERROR: UNKNOWN_COMMAND")
        expect(f"{port} invalid param", send_cmd(ser, "AT+SF=13"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid freq low", send_cmd(ser, "AT+FREQ=409999999"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid freq high", send_cmd(ser, "AT+FREQ=525000001"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid pwr low", send_cmd(ser, "AT+PWR=1"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid pwr high", send_cmd(ser, "AT+PWR=23"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid bw", send_cmd(ser, "AT+BW=3"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} invalid cr", send_cmd(ser, "AT+CR=5"), "#ERROR: OUT_OF_RANGE")
        expect(f"{port} bad payload", send_cmd(ser, "AT+SEND=ABC"), "#ERROR: BAD_PAYLOAD")
        expect(f"{port} nonhex payload", send_cmd(ser, "AT+SEND=GG"), "#ERROR: BAD_PAYLOAD")

        expect(f"{port} sleep", send_cmd(ser, "AT+SLEEP"), "OK")
        expect(f"{port} sleep guard RX", send_cmd(ser, "AT+RX=ON"), "#ERROR: RADIO_SLEEPING (send AT+WAKE)")
        expect(f"{port} sleep guard SEND", send_cmd(ser, "AT+SEND=AA"), "#ERROR: RADIO_SLEEPING (send AT+WAKE)")
        expect(f"{port} sleep guard FREQ", send_cmd(ser, "AT+FREQ=433000000"), "#ERROR: RADIO_SLEEPING (send AT+WAKE)")
        expect(f"{port} wake", send_cmd(ser, "AT+WAKE"), "OK")

        expect(f"{port} default", send_cmd(ser, "AT+DEFAULT", 0.25), "OK")
        expect(
            f"{port} default cfg",
            send_cmd(ser, "AT+CFG?"),
            "FREQ=433000000",
            "CHAN=0",
            "PWR=14",
            "SF=7",
            "BW=125000",
            "CR=4/5",
            "RX=OFF",
            "SLEEP=0",
            "OK",
        )
        restore_working_config(ser, port)


def wait_for(ser, token, label, timeout=3.0):
    data = bytearray()
    deadline = time.time() + timeout

    while time.time() < deadline:
        waiting = ser.in_waiting
        if waiting:
            data.extend(ser.read(waiting))
            text = bytes(data).decode(errors="replace")
            if token in text:
                print(f"--- {label} ---")
                print(normalize(text))
                return text
        else:
            time.sleep(0.02)

    text = bytes(data).decode(errors="replace")
    print(f"--- {label} timeout ---")
    print(normalize(text))
    raise RuntimeError(f"{label}: missing {token}")


def expect_now_or_wait(label, initial, ser, token):
    if token in initial:
        print(f"--- {label} ---")
        print(normalize(initial))
        return initial
    return wait_for(ser, token, label)


def run_radio_tests():
    with open_port("COM20") as a, open_port("COM21") as b:
        restore_working_config(a, "COM20")
        restore_working_config(b, "COM21")

        payload_ab = "524130385F54455354"
        expect("COM21 RX on", send_cmd(b, "AT+RX=ON"), "OK")
        tx_out = send_cmd(a, f"AT+SEND={payload_ab}", 0.2)
        expect("COM20 send", tx_out, "OK")
        expect_now_or_wait("COM20 txdone", tx_out, a, "+TXDONE")
        wait_for(b, "+RX:", "COM21 rx")
        expect("COM21 lastpkt", send_cmd(b, "AT+LASTPKT?"), "+LASTPKT:", payload_ab, "OK")
        expect("COM21 RX off", send_cmd(b, "AT+RX=OFF"), "OK")

        payload_ba = "524130385F4241434B"
        expect("COM20 RX on", send_cmd(a, "AT+RX=ON"), "OK")
        tx_out = send_cmd(b, f"AT+SEND={payload_ba}", 0.2)
        expect("COM21 send", tx_out, "OK")
        expect_now_or_wait("COM21 txdone", tx_out, b, "+TXDONE")
        wait_for(a, "+RX:", "COM20 rx")
        expect("COM20 lastpkt", send_cmd(a, "AT+LASTPKT?"), "+LASTPKT:", payload_ba, "OK")
        expect("COM20 RX off", send_cmd(a, "AT+RX=OFF"), "OK")

        restore_working_config(a, "COM20")
        restore_working_config(b, "COM21")


def run_manual_frequency_tests():
    payload_ab = "524130385F4D414E31"
    payload_ba = "524130385F4D414E32"

    with open_port("COM20") as a, open_port("COM21") as b:
        for ser, port in ((a, "COM20"), (b, "COM21")):
            expect(f"{port} default", send_cmd(ser, "AT+DEFAULT", 0.25), "OK")
            expect(f"{port} chan default", send_cmd(ser, "AT+CHAN?"), "+CHAN:0", "OK")
            expect(f"{port} manual freq", send_cmd(ser, "AT+FREQ=434000000"), "OK")
            expect(f"{port} manual cfg", send_cmd(ser, "AT+CFG?"), "FREQ=434000000", "CHAN=-1", "OK")
            expect(f"{port} manual chan", send_cmd(ser, "AT+CHAN?"), "+CHAN:-1 (manual frequency)", "OK")

        expect("COM21 manual RX on", send_cmd(b, "AT+RX=ON"), "OK")
        tx_out = send_cmd(a, f"AT+SEND={payload_ab}", 0.2)
        expect("COM20 manual send", tx_out, "OK")
        expect_now_or_wait("COM20 manual txdone", tx_out, a, "+TXDONE")
        wait_for(b, payload_ab, "COM21 manual rx")
        expect("COM21 manual RX off", send_cmd(b, "AT+RX=OFF"), "OK")

        expect("COM20 manual RX on", send_cmd(a, "AT+RX=ON"), "OK")
        tx_out = send_cmd(b, f"AT+SEND={payload_ba}", 0.2)
        expect("COM21 manual send", tx_out, "OK")
        expect_now_or_wait("COM21 manual txdone", tx_out, b, "+TXDONE")
        wait_for(a, payload_ba, "COM20 manual rx")
        expect("COM20 manual RX off", send_cmd(a, "AT+RX=OFF"), "OK")

        for ser, port in ((a, "COM20"), (b, "COM21")):
            expect(f"{port} channel 0", send_cmd(ser, "AT+CHAN=0"), "OK")
            expect(f"{port} channel cfg", send_cmd(ser, "AT+CFG?"), "FREQ=433000000", "CHAN=0", "OK")

        payload_ab = "524130385F43483031"
        payload_ba = "524130385F43483032"
        expect("COM21 ch0 RX on", send_cmd(b, "AT+RX=ON"), "OK")
        tx_out = send_cmd(a, f"AT+SEND={payload_ab}", 0.2)
        expect("COM20 ch0 send", tx_out, "OK")
        expect_now_or_wait("COM20 ch0 txdone", tx_out, a, "+TXDONE")
        wait_for(b, payload_ab, "COM21 ch0 rx")
        expect("COM21 ch0 RX off", send_cmd(b, "AT+RX=OFF"), "OK")

        expect("COM20 ch0 RX on", send_cmd(a, "AT+RX=ON"), "OK")
        tx_out = send_cmd(b, f"AT+SEND={payload_ba}", 0.2)
        expect("COM21 ch0 send", tx_out, "OK")
        expect_now_or_wait("COM21 ch0 txdone", tx_out, b, "+TXDONE")
        wait_for(a, payload_ba, "COM20 ch0 rx")
        expect("COM20 ch0 RX off", send_cmd(a, "AT+RX=OFF"), "OK")

        restore_working_config(a, "COM20")
        restore_working_config(b, "COM21")


def main():
    for port in PORTS:
        run_basic_tests(port)
    run_manual_frequency_tests()
    run_radio_tests()
    print("RA08_REGRESSION_PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"RA08_REGRESSION_FAIL: {exc}")
        sys.exit(1)
