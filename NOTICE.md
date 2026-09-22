# Code Origin and Third-Party Licenses

This project **does not contain a kernel driver or a `.ko` module**. SSD1306 panel support is handled entirely in user space, using stock Armbian/Linux components:

| Layer | Component | Origin |
|---|---|---|
| Pinmux / I2C controller | `sun50i-a64-i2c1.dtbo` (overlay) + `mv64xxx_i2c` driver + `i2c-dev` | mainline Linux / Armbian (stock) |
| SSD1306 panel driver | `luma.oled` (`luma.core.interface.serial.i2c`, `luma.oled.device.ssd1306`) | [rm-hull/luma.core](https://github.com/rm-hull/luma.core), [rm-hull/luma.oled](https://github.com/rm-hull/luma.oled) — **MIT** license, © Richard Hull |
| Bus | `smbus2` | © Karl-Johan Alm — **MIT** license |
| Graphics / fonts | `Pillow` | © Jeffrey A. Clark and contributors — **MIT-CMU / HPND** license |
| HTTP backend | `Flask` | © Pallets — **BSD-3-Clause** license |
| WSGI server | `waitress` | © Zope Foundation and contributors — **ZPL-2.1** license |

The code in this repository merely **uses** the libraries above (via imports), so it can be distributed under its own license.

> **TO VERIFY BEFORE PUBLISHING:** If `oled_test.py` / `oled_i2c_probe.py` contain snippets *copied and pasted* from `rm-hull/luma.*`, `karabek/OrangePi-OLED`, or `adafruit/Adafruit_Python_SSD1306`, their license headers and attributions must be preserved within those files and added to the table above. Standard library usage (imports) does not require this.
