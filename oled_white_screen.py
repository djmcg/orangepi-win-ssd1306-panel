#!/usr/bin/env python3
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image

def main():
    serial = i2c(port=1, address=0x3C)
    device = ssd1306(serial, width=128, height=32)

    image = Image.new("1", (device.width, device.height), 1)
    device.display(image)
    print("White screen displayed")

if __name__ == "__main__":
    main()
