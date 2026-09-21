#!/usr/bin/env python3
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from PIL import Image, ImageDraw
import time

def main():
    serial = i2c(port=1, address=0x3C)
    device = ssd1306(serial, width=128, height=32)

    print("Display initialized:", device.width, "x", device.height)
    print("Showing white full screen...")
    image = Image.new("1", (device.width, device.height), 1)
    device.display(image)
    time.sleep(2)

    print("Setting contrast to 0xCF...")
    device.contrast(0xCF)
    time.sleep(1)

    print("Showing test pattern...")
    img = Image.new("1", (128, 32), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 127, 31), outline=1, fill=0)
    draw.text((10, 10), "TEST 128x32", fill=1)
    device.display(img)
    time.sleep(2)

    print("Clearing...")
    device.clear()
    time.sleep(1)

    print("Showing white again...")
    device.display(Image.new("1", (128, 32), 1))
    time.sleep(2)

    print("Done")

if __name__ == "__main__":
    main()
