#!/usr/bin/env python3
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image
import time
import sys

def main():
    print("Init I2C...", flush=True)
    serial = i2c(port=1, address=0x3C)
    print("Init device 128x32...", flush=True)
    device = ssd1306(serial, width=128, height=32)
    print("Device: %dx%d" % (device.width, device.height), flush=True)

    img = Image.new("1", (device.width, device.height), 1)
    print("Display white...", flush=True)
    device.display(img)
    print("White screen displayed", flush=True)

    try:
        print("Keeping display on. Ctrl+C to exit.", flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exit", flush=True)
        sys.exit(0)

if __name__ == "__main__":
    main()
