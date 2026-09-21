#!/usr/bin/env python3
"""Bit-banged I2C probe for the SSD1306 OLED on the Orange Pi Win.

Rescue/diagnostic tool: talks to the display over plain GPIO lines (sysfs
interface), so it works even when the kernel I2C bus does not exist yet
(e.g. before the "i2c1" device tree overlay is enabled).

Wiring on the 40-pin header:
    OLED SDA -> pin 3 -> PH3 -> sysfs GPIO 227
    OLED SCL -> pin 5 -> PH2 -> sysfs GPIO 226
    OLED VCC -> pin 4 (5 V, module has its own 3.3 V LDO)
    OLED GND -> pin 6 or 9

Usage:
    oled_i2c_probe.py               # probe address 0x3c
    oled_i2c_probe.py --scan        # scan the whole address range
    oled_i2c_probe.py --delay 50    # slower clock (half period in us)
"""
import argparse
import os
import sys
import time

GPIO_ROOT = "/sys/class/gpio"

# pin number = (position of the bank letter in the alphabet - 1) * 32 + pin
PH2 = 226  # TWI1-SCK, header pin 5
PH3 = 227  # TWI1-SDA, header pin 3

DEFAULT_ADDRESS = 0x3C


class GpioLine:
    """A single GPIO line driven through the sysfs interface."""

    def __init__(self, number, root=GPIO_ROOT):
        self.number = number
        self.root = root
        self.path = os.path.join(root, "gpio%d" % number)
        if not os.path.isdir(self.path):
            with open(os.path.join(root, "export"), "w") as handle:
                handle.write(str(number))
            deadline = time.time() + 2
            while not os.path.isdir(self.path) and time.time() < deadline:
                time.sleep(0.02)
        if not os.path.isdir(self.path):
            raise OSError("cannot export GPIO %d (line in use?)" % number)
        self._direction = os.path.join(self.path, "direction")
        self._value = os.path.join(self.path, "value")
        self._write_fd = os.open(self._value, os.O_WRONLY)
        self._read_fd = os.open(self._value, os.O_RDONLY)
        self.release()

    def _set_direction(self, value):
        with open(self._direction, "w") as handle:
            handle.write(value)

    def drive_low(self):
        self._set_direction("low")

    def drive_high(self):
        self._set_direction("high")

    def release(self):
        """High impedance - the external pull-up pulls the line high."""
        self._set_direction("in")

    def read(self):
        return os.pread(self._read_fd, 1, 0) == b"1"

    def cleanup(self):
        os.close(self._write_fd)
        os.close(self._read_fd)
        try:
            with open(os.path.join(self.root, "unexport"), "w") as handle:
                handle.write(str(self.number))
        except OSError:
            pass


class BitBangI2C:
    """Minimal I2C master: only what is needed to probe a slave address."""

    def __init__(self, sda, scl, delay):
        self.sda = sda
        self.scl = scl
        self.delay = delay
        self.scl.drive_high()
        self.sda.release()
        time.sleep(0.002)

    def _half(self):
        if self.delay:
            time.sleep(self.delay)

    def start(self):
        self.sda.release()
        self.scl.drive_high()
        self._half()
        self.sda.drive_low()
        self._half()
        self.scl.drive_low()
        self._half()

    def stop(self):
        self.sda.drive_low()
        self._half()
        self.scl.drive_high()
        self._half()
        self.sda.release()
        self._half()

    def write_byte(self, value):
        for bit in range(7, -1, -1):
            if value & (1 << bit):
                self.sda.release()
            else:
                self.sda.drive_low()
            self._half()
            self.scl.drive_high()
            self._half()
            self.scl.drive_low()
            self._half()
        self.sda.release()
        self._half()
        self.scl.drive_high()
        self._half()
        acknowledged = not self.sda.read()
        self.scl.drive_low()
        self._half()
        return acknowledged

    def probe(self, address):
        """Send a write address byte and report whether the slave ACKed."""
        self.start()
        acknowledged = self.write_byte(address << 1)
        self.stop()
        return acknowledged


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bit-banged I2C probe for SSD1306 on Orange Pi Win")
    parser.add_argument("--sda", type=int, default=PH3,
                        help="GPIO number of SDA (default: %d = PH3)" % PH3)
    parser.add_argument("--scl", type=int, default=PH2,
                        help="GPIO number of SCL (default: %d = PH2)" % PH2)
    parser.add_argument("--address", default="0x3c",
                        help="I2C address to probe (default: 0x3c)")
    parser.add_argument("--scan", action="store_true",
                        help="scan all addresses from 0x03 to 0x77")
    parser.add_argument("--delay", type=float, default=20.0,
                        help="half clock period in microseconds (default: 20)")
    args = parser.parse_args(argv)

    print("bit-banged I2C: SDA=gpio%d, SCL=gpio%d, half period %.1f us"
          % (args.sda, args.scl, args.delay))

    sda = GpioLine(args.sda)
    scl = GpioLine(args.scl)
    bus = BitBangI2C(sda, scl, args.delay / 1000000.0)
    try:
        if args.scan:
            found = [addr for addr in range(0x03, 0x78) if bus.probe(addr)]
            if found:
                for address in found:
                    print("device found at 0x%02x" % address)
            else:
                print("no device answered")
            return 0 if found else 2

        address = int(args.address, 0)
        if bus.probe(address):
            print("ACK from 0x%02x - display detected" % address)
            return 0
        print("no ACK from 0x%02x - check VCC/GND, SDA=pin3, SCL=pin5 and "
              "the pull-ups on the module" % address)
        return 2
    finally:
        sda.cleanup()
        scl.cleanup()


if __name__ == "__main__":
    sys.exit(main())