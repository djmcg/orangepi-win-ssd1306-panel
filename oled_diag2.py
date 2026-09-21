#!/usr/bin/env python3
"""Diagnostic script for SSD1306 OLED on Orange Pi Win."""
import time
import sys

# Try importing required modules
try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from PIL import Image
except ImportError as e:
    print("ERROR: Missing module: %s" % e)
    sys.exit(1)

def main():
    print("Creating I2C interface...")
    serial = i2c(port=1, address=0x3C)
    print("I2C interface created")
    
    print("Creating ssd1306 device (128x32)...")
    try:
        device = ssd1306(serial, width=128, height=32)
        print("Device created: %dx%d" % (device.width, device.height))
    except Exception as e:
        print("ERROR creating device: %s" % e)
        return
    
    print("Displaying white screen...")
    try:
        image = Image.new("1", (device.width, device.height), 1)
        device.display(image)
        print("White screen sent")
    except Exception as e:
        print("ERROR displaying image: %s" % e)
        return
    
    print("Waiting 10 seconds - check display now")
    for i in range(10, 0, -1):
        print("%d..." % i)
        time.sleep(1)
    
    print("\nDone. Display should still show white.")

if __name__ == "__main__":
    main()
