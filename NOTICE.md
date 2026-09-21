# Pochodzenie kodu i licencje stron trzecich

Ten projekt **nie zawiera sterownika jądra ani modułu `.ko`**. Obsługa panelu
SSD1306 odbywa się w całości w przestrzeni użytkownika, na stockowych
komponentach Armbian/Linux:

| Warstwa | Komponent | Pochodzenie |
|---|---|---|
| Pinmux / kontroler I2C | `sun50i-a64-i2c1.dtbo` (overlay) + sterownik `mv64xxx_i2c` + `i2c-dev` | mainline Linux / Armbian (stock) |
| Sterownik panelu SSD1306 | `luma.oled` (`luma.core.interface.serial.i2c`, `luma.oled.device.ssd1306`) | [rm-hull/luma.core](https://github.com/rm-hull/luma.core), [rm-hull/luma.oled](https://github.com/rm-hull/luma.oled) — licencja **MIT**, © Richard Hull |
| Magistrala | `smbus2` | © Karl-Johan Alm — licencja **MIT** |
| Grafika / fonty | `Pillow` | © Jeffrey A. Clark i kontrybutorzy — licencja **MIT-CMU / HPND** |
| Backend HTTP | `Flask` | © Pallets — licencja **BSD-3-Clause** |
| Serwer WSGI | `waitress` | © Zope Foundation i kontrybutorzy — licencja **ZPL-2.1** |

Kod w tym repozytorium jedynie **korzysta** z powyższych bibliotek (importy),
więc może być rozpowszechniany na własnej licencji.

> **DO WERYFIKACJI PRZED PUBLIKACJĄ:** jeśli w `oled_test.py` /
> `oled_i2c_probe.py` znajdują się fragmenty *przeniesione* (kopiuj-wklej) z
> `rm-hull/luma.*`, `karabek/OrangePi-OLED` lub `adafruit/Adafruit_Python_SSD1306`,
> to ich nagłówki licencyjne i atrybucję trzeba zachować w tych plikach oraz
> dopisać do tabeli powyżej. Użycie biblioteczne (import) tego nie wymaga.
