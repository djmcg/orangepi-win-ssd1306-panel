# OLED status panel for Orange Pi Win (SSD1306 128x32 over I2C)
<img width="928" height="1159" alt="image" src="https://github.com/user-attachments/assets/246bcffd-bcad-4346-9103-b5049bffdc3c" />


Live system status plus an interactive web console for a 0.91" SSD1306 OLED wired
to the 40-pin header of an **Orange Pi Win** (Allwinner A64, `sun50iw1`, Armbian).

<!-- Add your own photo as `oled-panel.jpg` in the repo root, then uncomment:
![Orange Pi Win with the SSD1306 panel](oled-panel.jpg)
-->

One Python process (deployed as a systemd service) does three things at once:

1. renders a 128x32 1-bit frame and pushes it to the panel over `/dev/i2c-1`,
2. serves a small Flask REST API (`/api/...`) that changes what the screen shows,
3. writes a live JSON status file and a PNG snapshot of the rendered frame for the web panel.

## Features

- **Default screen:** board name, live date/time, CPU temperature (1 s refresh).
- **Web dashboard** (dark theme): live frame preview, system cards, command console, screen history.
- **Command agent:** switch modes, show temperature/clock, or push any text auto-formatted into 1, 2 or 3 lines.
- **Screen history:** last 20 entries, each with a one-click "restore to panel" button.
- **Image mode:** upload a PNG/JPG, it is padded, dithered to 1-bit and sent to the panel.
- **Horizontal scrolling** for text wider than the panel.
- **Self-healing:** a failed I2C write is logged instead of killing the service; the render loop retries device init.
- **Runs headless:** with no working bus it starts in simulation mode and the web API stays up.

## Scope note (read this first)

This is **not** a kernel driver. There is no `.ko`, no patched device tree. It uses:

- stock Armbian overlay `sun50i-a64-i2c1.dtbo`,
- stock mainline `mv64xxx_i2c` + `i2c-dev`,
- [`luma.oled`](https://github.com/rm-hull/luma.oled) (userspace SSD1306/SH1106 driver), Pillow, Flask.

What *is* non-obvious on this board: header pins 3/5 are **I2C1, not I2C0**
(see below), and I2C1 on this SoC can silently *latch* (see Troubleshooting).

## Wiring

| OLED module | Orange Pi Win 40-pin | SoC pin | sysfs GPIO | Function |
|---|---|---|---|---|
| SDA | pin 3 | PH3 | 227 | TWI1-SDA |
| SCL | pin 5 | PH2 | 226 | TWI1-SCK |
| VCC | pin 4 (5 V) | — | — | module has its own 3.3 V LDO |
| GND | pin 6 (or 9) | — | — | — |

- Panel: SSD1306, 128x32 (0.91"), address `0x3c`, bus `/dev/i2c-1`.
- 0.96" module (128x64)? run with `--height 64`.
- Panel shows garbage or is all white? it may be an SH1106 controller: `--driver sh1106`.
- The board used for this project has a dead DC jack, so the whole board is powered
  from pin 2 (5 V) + pin 6 (GND). Pin 1 (3.3 V) is deliberately left free so it does
  not interfere with the AXP803 PMIC.

## Enable I2C1 (the part everyone gets wrong)

Pins 3/5 of the Win header are wired to **TWI1**, therefore `overlays=i2c1`.
The `i2c0` overlay uses PH0/PH1, which are **not routed** to the 40-pin header --
enabling it will never make your display appear, no matter what other guides say.

First find out which `armbianEnv.txt` u-boot actually reads (on a
"boot on SD card, rootfs on USB" setup the `/boot` you see on the rootfs can be a
different, empty mount):

```bash
cat /proc/cmdline        # note ubootpart=<PARTUUID>
findmnt /boot            # which device backs /boot ?
```

Then edit the live file:

```bash
cp /boot/armbianEnv.txt /boot/armbianEnv.txt.bak
sed -i 's/^overlays=.*/overlays=i2c1/' /boot/armbianEnv.txt
sync && sudo reboot
```

Verify:

```bash
i2cdetect -l              # mv64xxx_i2c adapter -> /dev/i2c-1
timeout 5 i2cdetect -y 1  # 0x3c must appear
```

Always wrap `i2cdetect` in `timeout`: when the bus is latched it hangs forever in
uninterruptible sleep (state `D`).

Rollback: `cp /boot/armbianEnv.txt.bak /boot/armbianEnv.txt`

## Install

```bash
sudo apt install i2c-tools python3-flask python3-pil python3-smbus2 python3-waitress fonts-dejavu-core
python3 -m pip install luma.oled --break-system-packages   # or use a virtualenv
```

Flask on the reference machine came from APT (3.1.1 with Werkzeug 3.1.3).
See `requirements.txt` for the full dependency list and `NOTICE.md` for licenses.

## Run

```bash
sudo python3 oled_test.py                                  # auto-detect bus, 128x32, port 5003
python3 oled_test.py --height 64 --driver sh1106           # 0.96" / SH1106 module
python3 oled_test.py --bus 1 --address 0x3c --interval 1 --port 5003
```

| Option | Default | Meaning |
|---|---|---|
| `--bus` | auto-detect | I2C bus number (probes every `/dev/i2c-*` for the address) |
| `--address` | `0x3c` | panel I2C address |
| `--width` / `--height` | `128` / `32` | panel geometry |
| `--driver` | `ssd1306` | `ssd1306` or `sh1106` |
| `--interval` | `1.0` | refresh interval in seconds |
| `--port` | `5003` | Flask API port |
| `--status-json` | `/var/www/oled/oled-status.json` | live status for the web page |
| `--frame-png` | `/var/www/oled/oled-frame.png` | rendered frame for the preview |

Offline smoke test with no display attached: `python3 oled_test.py --bus 9` --
the API still answers and the device falls back to simulation.

## systemd

```bash
sudo cp deploy/oled-test.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oled-test
systemctl status oled-test
journalctl -u oled-test -f
```

## Web panel

`index.html` / `app.js` use absolute paths (`/oled/...`, `/api/...`), so serve the
directory at `/oled/` and reverse-proxy `/api/` to the Flask port:

```bash
sudo cp deploy/nginx-oled.conf /etc/nginx/snippets/oled.conf
# add:  include snippets/oled.conf;   inside your server{} block (root /var/www)
sudo nginx -t && sudo systemctl reload nginx
```

Panel: `http://<board>/oled/`

## API

| Method | Path | Body | Purpose |
|---|---|---|---|
| GET | `/api/status` | — | current state: `rows`, `mode`, `renderMode`, `cpuTemp`, `uptime`, `pid`, `updated` |
| POST | `/api/command` | `{"input":"...","lines_count":"auto"}` | command agent or free text (`lines_count`: `auto`, `1`, `2`, `3`, `max`) |
| GET | `/api/history` | — | `{"history":[...]}` - last 20 entries |
| POST | `/api/history/restore/<id>` | — | re-send a history entry to the panel |
| POST | `/api/upload-image` | multipart `image` (max 5 MB) | image mode - padded, dithered to 1-bit |

```bash
curl -s localhost:5003/api/status | python3 -m json.tool
curl -s -X POST localhost:5003/api/command -H 'Content-Type: application/json' -d '{"input":"temp"}'
curl -s -X POST localhost:5003/api/command -H 'Content-Type: application/json' -d '{"input":"Server alarm","lines_count":2}'
curl -s -X POST localhost:5003/api/history/restore/1a2b3c4d
curl -s -F image=@logo.png localhost:5003/api/upload-image
```

## Command agent

| Input | Effect |
|---|---|
| `domyslny`, `reset`, `system`, `default` | back to SYSTEM_DEFAULT (name / clock / CPU temperature) |
| `temp`, `temperatura`, `cpu` | thermal screen |
| `zegar`, `czas`, `time`, `clock` | enlarged clock screen |
| anything else | word-wrapped into 1, 2 or 3 lines (16-18 chars per line); if it is too wide for a single line the renderer switches to horizontal scroll |

Modes: `SYSTEM_DEFAULT`, `CUSTOM`, `IMAGE`, `SCROLL_H`, `DIAGNOSTICS`.
Fonts are chosen automatically per line count, so one line renders large and three
lines fall back to a small monospaced face inside 32 px.

## Troubleshooting

### 1. Black screen, service "running": latched I2C bus

Symptom: `dmesg` fills with `i2c i2c-1: mv64xxx: I2C bus locked, block: 1, time_left: 0`,
`i2cdetect -y 1` hangs (exit 124 even under `timeout`), `i2cdetect` processes stuck in
state `D`, while `oled-status.json` and `oled-frame.png` stay fresh.

Fix - no reboot needed:

```bash
sudo oled-recover            # after installing deploy/oled-recover
# or manually:
systemctl stop oled-test; pkill -9 i2cdetect
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/unbind; sleep 2
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind;   sleep 3
timeout 5 i2cdetect -y 1 ; echo "exit=$?"
systemctl start oled-test
```

### 2. Black glass, healthy bus: the panel never got its init sequence

The bus is fine (`bus locked` count is not growing, `0x3c` is visible, the PNG keeps
updating) but the glass stays dark - typically after a cold-boot kernel error window
(`Ctlr Error status 0x38`). This is not a bus fault.

Fix: `sudo systemctl restart oled-test`. Current builds also self-heal: after 5
consecutive write failures the render loop rebuilds the device and re-sends init
(30 s cooldown).

### 3. Service alive but frozen: userspace deadlock

`oled-frame.png` stops changing, `/api/status` times out, and the thread count
(`ps -o nlwp -C python3`) climbs into the hundreds. The bus is healthy here - do
**not** touch it.

Fix: `sudo systemctl restart oled-test`. The shipped watchdog automates this without
fighting an intentional `oled-recover` (every minute it checks the frame age, the file
descriptor count and the thread count):

```bash
sudo install -m 755 deploy/oled-watchdog /usr/local/sbin/oled-watchdog
sudo cp deploy/oled-watchdog.service deploy/oled-watchdog.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now oled-watchdog.timer
```

Cron equivalent, kept for people who prefer cron over timers:

```cron
* * * * * systemctl is-active --quiet oled-test && ! find /var/www/oled/oled-frame.png -mmin -1 | grep -q . && systemctl restart oled-test
```

A guard for the same job in the old cron entry was left commented out on this machine,
which is exactly why the wedge described in item 4 went unnoticed for a day.

### 4. Writes stopped while the API still answers: file descriptor exhaustion

Observed once in production (2026-09-21): the service stayed `active` and kept
answering `/api/status` from memory, but `oled-status.json` and `oled-frame.png`
froze, and the process had burned 26 h of CPU time. The journal showed:

```
cannot write /var/www/oled/oled-status.json: [Errno 24] Too many open files: '...tmp'
```

The render loop never crashes on this: `write_text_atomic` / `write_image_atomic`
only print the error, so the failure is silent unless you check file mtimes.
Restarting the service clears it; `oled-watchdog` (item 3) catches it automatically,
because a stale frame is the only visible symptom.

Since 2026-09-21 the API is served by waitress with a fixed worker pool (`--threads`,
default 8) instead of the Flask development server, and the auto re-init path closes the
previous luma device handle (`release_device()`), removing the two known sources of
descriptor growth.

Diagnose:

```bash
P=$(systemctl show -p ExecMainPID --value oled-test)
ls /proc/$P/fd | wc -l                                        # thousands = leaking
ls -l /proc/$P/fd | sed 's/.*-> //' | sort | uniq -c | sort -rn | head
```

### 5. The web preview can lie

`oled-frame.png` is generated from the *render*, not read back from the panel. With a
latched bus or a de-initialised panel the page still shows a fresh frame and a green
"online" dot while the glass is black. Always cross-check the kernel log for
`bus locked` lines.

There is no true readback over I2C - the SSD1306 GDDRAM is write-only from the host
side - so a software mirror is the only affordable preview, and it must be labelled as
such.

### 6. Only one process may own the panel

Anything that talks to the OLED must run while `oled-test` is stopped, otherwise you get
`Input/output error` / `Remote I/O error`. That applies to the bundled luma test scripts
and to the bit-bang probe.

### 7. Quick triage

| Symptom | Check | Fix |
|---|---|---|
| No `/dev/i2c-1` | `overlays=i2c1`, `.dtbo` present, pinmux | enable I2C1 (see above) |
| Bus exists, no `0x3c` | `timeout 5 i2cdetect -y 1` | wiring, VCC on pin 4, swap SDA/SCL |
| Bus latched | kernel log shows `bus locked` | `oled-recover` |
| Dark glass, bus healthy | PNG updating and `0x3c` visible | restart the service (auto re-init) |
| Garbage or inverted image | — | try `--driver sh1106`, check `--height` |
| PNG frozen, API silent | `ps -o nlwp -C python3` | restart the service (item 3) |

## Tools in this repo

| File | Role |
|---|---|
| `oled_test.py` | the service: render loop + Flask API + history + command parser |
| `index.html`, `app.js` | web panel served at `/oled/` |
| `oled_i2c_probe.py` | rescue bit-bang I2C over sysfs GPIO, works even when no kernel bus exists (`--scan`) |
| `deploy/oled-test.service` | systemd unit |
| `deploy/nginx-oled.conf` | nginx snippet (static `/oled/` + proxy `/api/`) |
| `deploy/oled-recover` | latched-bus recovery script, install to `/usr/local/sbin` |
| `deploy/oled-watchdog` + `.service`/`.timer` | restarts the service when the frame goes stale, descriptors leak or threads explode |
| `README-oled.md` | the full Polish incident log from the original repair session |
| `NOTICE.md` | third-party components and their licenses |

The bit-bang probe requires the `i2c1` controller to be detached first, otherwise GPIO
export fails with `line in use`.

`oled_raw_i2c.py` (raw 512-byte block writes) is intentionally **not published** - see
`.gitignore`. It drives the panel with mismatched SMBus helpers and is the prime suspect
for latching the bus; `luma.oled` sends a correct init sequence instead.

## Limitations and known issues

- One process per panel - there is no cross-process locking.
- Image mode: 5 MB upload limit, Floyd-Steinberg dithering, target geometry from the flags.
- `/api/status` reports the rendered state, not a readback from the glass (item 5).
- The service can leak file descriptors over days and keep reporting `active` while
  status/PNG writes fail (item 4) - install `oled-watchdog` (item 3).
- Default geometry is 128x32; 0.96" modules need `--height 64`.
- The API runs on waitress (fixed worker pool, `--threads`, default 8). Without waitress
  the code falls back to the Flask development server, which churns threads and file
  descriptors under long-running polling (see item 4).
- No authentication in the web panel: keep it on your LAN or add auth yourself.

## Credits and license

MIT, see [LICENSE](LICENSE).

Built on [luma.core / luma.oled](https://github.com/rm-hull/luma.oled)
(MIT, (c) Richard Hull), `smbus2` (MIT, (c) Karl-Johan Alm), Pillow (MIT-CMU) and
Flask (BSD-3-Clause). Full list in [NOTICE.md](NOTICE.md).

This project is not a kernel driver and does not replace one. It is a working
integration recipe plus field notes for a board/panel combination that is easy to get
wrong: I2C1 instead of I2C0, a latched I2C bus, and a renderer that keeps painting while
the glass stays black.


