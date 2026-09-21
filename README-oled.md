# OLED SSD1306 na Orange Pi Win — README i instrukcja naprawy

> **STATUS: NAPRAWIONE 2026-09-19 07:52 CEST — wyświetlacz znów działa.**
> Przyczyna była sprzętowo-sterownikowa: **zatrzaśnięta magistrala I2C1**
> (`mv64xxx: I2C bus locked`, 350 wpisów w `dmesg`). Panel trzymał linię SDA
> w stanie niskim.
> **Skuteczna naprawa (3 polecenia, bez restartu systemu):**
> `systemctl stop oled-test` → `echo 1c2b000.i2c > .../mv64xxx_i2c/unbind`
> → `echo 1c2b000.i2c > .../mv64xxx_i2c/bind`.
> Szczegóły i pełna procedura: **sekcja 5**. Potwierdzenie: **sekcja 3.5**.
> Gotowe narzędzie jednym poleceniem: **`oled-recover`** (sekcja 15.5).
> **Incydent 2 (08:11 CEST):** usługa cicho zamarła w userspace (deadlock:
> PNG stał od 07:57:04, API odpowiadało pustką, 193 wątków). Pomógł sam
> `systemctl restart oled-test` — szyna I2C była wtedy **zdrowa**. Szczegóły: **sekcja 15.7**.
> **Incydent 3 (ok. 09:09 CEST):** po zimnym starcie okno błędów I2C (kernel
> `Ctlr Error status 0x38`, 08:52:23–08:53:01) zostawiło panel **bez initu** —
> szyna i API zdrowe, PNG świeży, a szkło czarne. Naprawa: restart usługi (re-init).
> Utrwalono: **auto re-init** w `oled_test.py`, `RestartSec=3`, strażnik w cronie.
> Szczegóły: **sekcja 15.8**.

> Poniższe sekcje 1–4 opisują objawy i przyczynę (przydatne, jeśli problem wróci).
> Backup poprzedniej wersji: `README-oled.md.bak-20260919`.
>
> **Uwaga o podglądzie WWW:** `oled-frame.png` jest generowany z *renderu*,
> a nie odczytany z panelu — więc gdy I2C jest zablokowane, strona `/oled/`
> pokazuje klatkę, która **nie** dotarła na szkło (fałszywy „online”).

## 1. Objawy

- Ekran jest czarny (lub świeci na biało) i nie reaguje na komendy z panelu WWW.
- W `dmesg` co kilka sekund powtarza się:
  `i2c i2c-1: mv64xxx: I2C bus locked, block: 1, time_left: 0`
- `i2cdetect -y 1` **zawiesza się** (nawet pod `timeout` kończy się kodem `124`)
  i nie pokazuje urządzenia `0x3c`.
- Serwis `oled-test.service` jest `active (running)`, API odpowiada, pliki
  `oled-status.json` / `oled-frame.png` są świeże — mimo to ekran nic nie pokazuje.
- W `ps` wiszą procesy `i2cdetect` w stanie **D** (uninterruptible sleep).

## 2. Kluczowe dane maszyny (zweryfikowane poleceniami)

| Element | Wartość |
|---|---|
| Płytka | Orange Pi Win, rodzina `sun50iw1` / `sunxi64`, aarch64 |
| System | Armbian 26.11.0-trunk.51 trixie (Debian 13) |
| Jądro | `6.18.51-current-sunxi64` (SMP PREEMPT, 2026-09-11) |
| Start systemu | 2026-09-18 21:49 CET (uptime 9:43 w chwili diagnozy) |
| Partycja rozruchowa | **`/dev/sda1`** (ext4), montowana w **`/boot`** oraz `/media/boot-media` |
| Plik overlay | **`/boot/armbianEnv.txt`** → `overlays=i2c1` |
| Katalog overlayów | `/boot/dtb/allwinner/overlay` (`sun50i-a64-i2c1.dtbo`, 496 B) |
| Magistrala | `/dev/i2c-1` = `mv64xxx_i2c adapter` |
| Panel | SSD1306 128x32 (0.91", LDO 662K), adres **`0x3c`** |
| Pinmux | pin 226 (PH2)=SCL, pin 227 (PH3)=SDA, funkcja `i2c1`, kontroler `1c2b000.i2c` |
| Kontroler (unbind/bind) | `/sys/bus/platform/drivers/mv64xxx_i2c/`, urządzenie `1c2b000.i2c` |
| Serwis | `oled-test.service`, PID 29446, `NRestarts=0`, `Restart=always` |
| Backend | Flask **3.1.1** (apt `python3-flask`) + Werkzeug 3.1.3, port **5003** |
| Proxy WWW | nginx `location /api/` → `http://127.0.0.1:5003/api/` |

**Uwaga:** poprzednia dokumentacja mówiła o partycji `/dev/mmcblk0p1` i katalogu
`/mnt/bootpart`. **Na tej maszynie to nieprawda** — system startuje z
`/dev/sda1`, a `armbianEnv.txt` leży w `/boot/armbianEnv.txt`.

## 3. Diagnoza — co zostało sprawdzone (dowody)

### 3.1 Magistrala istnieje, ale jest zablokowana

```
$ dmesg | grep -i 'bus locked' | head -1
[34227.549781] i2c i2c-1: mv64xxx: I2C bus locked, block: 1, time_left: 0
```

Pierwsze wystąpienie przy uptime 34227 s ≈ **2026-09-19 07:20** — czyli dokładnie
wtedy, gdy w katalogu pojawiały się skrypty diagnostyczne (patrz sekcja 4).

```
$ ls -la /dev/i2c-1
crw-rw---- 1 root i2c 89, 1 /dev/i2c-1        # urządzenie istnieje

$ timeout 8 i2cdetect -y 1 ; echo "exit=$?"
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- exit=124        # ZAWIESZONE, brak 0x3c
```

Kod `124` = `timeout` musiał ubić proces. Skan w trybie szybkim (`-y`) i
„read” (`-y -r`) zachowują się identycznie — szyna nie odpowiada.

**Migawka z chwili pisania tego README (2026-09-19 07:43 CEST):**

```
$ dmesg | grep -c 'bus locked'
347
$ dmesg | grep 'bus locked' | tail -1
[35253.598648] i2c i2c-1: mv64xxx: I2C bus locked, block: 1, time_left: 0
$ cut -d' ' -f1 /proc/uptime
35599.28
```

Czyli blokada trwa nieprzerwanie (ostatni wpis ~5,7 min przed odczytem),
a licznik rośnie — magistrala **wciąż jest zatrzaśnięta**, dopóki nie wykonasz
sekcji 5. Serwis w tym czasie raportuje `"mode": "SYSTEM_DEFAULT"` i świeży
`updated`, mimo że na szkle nic się nie zmienia.

### 3.2 Zawieszone procesy trzymają magistralę (stan D)

```
$ ps -o pid,stat,wchan:30,cmd -C i2cdetect
    PID STAT WCHAN                          CMD
  30420 D+   rt_mutex_schedule              i2cdetect -y 1
  30686 D+   mv64xxx_i2c_wait_for_completio i2cdetect -y 1

$ fuser -v /dev/i2c-1
/dev/i2c-1:  root  29446 F.... python3        # usługa oled-test (właściciel)
             root  30420 F.... i2cdetect
             root  30686 F.... i2cdetect
```

`STAT=D+` + `WCHAN=mv64xxx_i2c_wait_for_completion` to dowód, że proces siedzi
w jądrze na zawsze. **Procesu w stanie D nie da się zabić**, dopóki sterownik
nie zwolni zasobu — dlatego kolejność naprawy ma znaczenie.

### 3.3 Pinmux i overlay są POPRAWNE (to nie jest problem device tree)

```
$ cat /sys/kernel/debug/pinctrl/*/pinmux-pins | grep -iE 'ph2|ph3'
pin 226 (PH2): 1c2b000.i2c (GPIO UNCLAIMED) function i2c1 group PH2
pin 227 (PH3): 1c2b000.i2c (GPIO UNCLAIMED) function i2c1 group PH3
```

Piny są prawidłowo przełączone na funkcję `i2c1` i zajęte przez kontroler
`1c2b000.i2c`. `overlays=i2c1` jest aktywne, plik `.dtbo` obecny.
**Nie ruszaj overlaya ani `armbianEnv.txt` — one działają.**

### 3.4 Usługa działa, ale klatka nie dociera do panelu

- `systemctl status oled-test` → `active (running)`, `NRestarts=0`.
- Logi pokazują obsłużone żądania HTTP (`GET /api/status`, `GET /api/history` → `200`).
- Kod łapie błąd zapisu do I2C i tylko go loguje (`I2C write error: ...`),
  więc usługa **nie pada** — dalej renderuje i zapisuje `oled-frame.png`
  oraz `oled-status.json`. Stąd „fałszywy online” na stronie `/oled/`.
- Brak jakiegokolwiek innego błędu jądra niż `bus locked`
  (`dmesg | grep -i i2c | grep -v 'bus locked'` → pusto).

### 3.5 Potwierdzenie naprawy (2026-09-19 07:52 CEST) — WYKONANE I DZIAŁA

Kolejność, która **faktycznie odblokowała** magistralę (bez restartu systemu):

```
systemctl stop oled-test                    # zwolnij /dev/i2c-1 (krok 1)
pkill -9 i2cdetect                          # uśmierć zawieszone procesy
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/unbind
sleep 2                                     # /dev/i2c-1 znika -> reset kontrolera
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind
sleep 3                                     # /dev/i2c-1 wraca (major 89, minor 1)
timeout 6 i2cdetect -y 1                    # WYNIK PONIŻEJ
systemctl start oled-test
```

Wynik, który potwierdza sukces (zrzut z wykonania):

```
$ timeout 6 i2cdetect -y 1 ; echo "exit=$?"
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- 3c -- -- -- -- --     <-- PANEL WIDOCZNY
70: -- -- -- -- -- -- -- --
exit=0                                                    <-- BRAK ZAWIESZENIA
```

Test zapisu na szkło (usługa zatrzymana, jeden proces na raz):

```
$ timeout 5 python3 /var/www/oled/oled_white_screen.py
White screen displayed          <-- ekran zrobił się biały, brak wyjątku I2C
```

Dowody, że dane realnie docierają do panelu **po** starcie usługi:

| Test | Wynik |
|---|---|
| `grep mv64xxx /proc/interrupts` (2×, odstęp 3 s) | `10237467` → `10237991` — **+524 przerwań** = realny ruch I2C |
| `journalctl -u oled-test --since '07:50' \| grep -ci 'I2C write error'` | **`0`** — żadnego błędu zapisu |
| Licznik `dmesg \| grep -c 'bus locked'` | zatrzymał się na **350** i nie rośnie |
| `md5sum oled-frame.png` (2×) | zmienia się → klatki są renderowane na bieżąco |
| `curl .../api/command -d '{"input":"temp"}'` | `success:true`, `rows:["OrangePi Win","CPU 59.2 C","10:01"]`, wpis w historii |
| `curl .../api/command -d '{"input":"reset"}'` | powrót do `mode: SYSTEM_DEFAULT` |

Co jest na ekranie po naprawie (tryb `SYSTEM_DEFAULT`):

```
OrangePi Win
2026-09-19 07:51:38
CPU 57.8 C
```

**Wniosek na przyszłość:** gdy `i2cdetect` znowu pokaże `exit=124`, wystarczy
powtórzyć dokładnie tę sekwencję (stop → unbind → bind). Restart systemu jest
konieczny tylko wtedy, gdy procesy zostaną w stanie `D` i unbind się nie powiedzie.

## 4. Przyczyna (root cause)

**Konkurencyjny dostęp do magistrali + przerwana transmisja do SSD1306.**

Ślady: w katalogu `/var/www/oled/` powstały 2026-09-19 o **07:16–07:21** skrypty
`oled_white_screen.py`, `oled_diag.py`, `oled_raw_i2c.py`, `oled_white.py`,
`oled_diag2.py` — czyli **w tym samym czasie (07:20), w którym pojawił się
pierwszy komunikat `I2C bus locked`**.

Najbardziej podejrzany jest `oled_raw_i2c.py`: wysyła „na surowo” bloki po
512 B (`write_i2c_block_data`) z własną, błędną sekwencją inicjalizacji.
W połączeniu z tym, że **usługa `oled-test.service` cały czas działała i używała
tej samej magistrali**, transakcja została przerwana w połowie — slave
(SSD1306) podtrzymał linię SDA w stanie niskim, a sterownik `mv64xxx_i2c`
wpadł w pętlę „bus locked” (to jądro nie ma tu sprzętowej procedury recovery
dla „bus busy” na tym SoC). Zawieszone `i2cdetect` w stanie `D` dopełniły obrazu,
blokując szynę również po zakończeniu tamtego skryptu.

Wnioski dla naprawiającego:
- To **nie** jest błąd kodu `oled_test.py` ani zły device tree/pinmux.
- To **nie** jest kwestia uprawnień (`root` ma dostęp do `/dev/i2c-1`).
- To zatrzaśnięta magistrala: trzeba ją **zresetować** (unbind/bind kontrolera),
  a jeśli panel nadal trzyma SDA — **odciąć mu zasilanie** (power-cycle).

## 5. Naprawa krok po kroku

### Krok 1 — zatrzymaj usługę i zabij zawieszone procesy

```
systemctl stop oled-test
pkill -9 i2cdetect
pkill -9 -f oled_diag ; pkill -9 -f oled_white ; pkill -9 -f oled_raw_i2c
ps -o pid,stat,cmd -C i2cdetect        # ma być pusty wynik
```

Jeśli procesy **nadal są w stanie `D`** (nie zniknęły po `-9`) — sterownik nie
zwolnił magistrali i **przejdź od razu do Kroku 7 (restart systemu)**.

### Krok 2 — zresetuj kontroler I2C (unbind/bind)

```
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/unbind
sleep 2
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind
sleep 2
dmesg | tail -5              # brak nowych "bus locked"
ls -la /dev/i2c-1            # urządzenie powinno wrócić
```

### Krok 3 — sprawdź, czy magistrala wróciła

```
timeout 5 i2cdetect -y 1 ; echo "exit=$?"
```

- `exit=0` i `3c` w tabeli → **magistrala naprawiona**, idź do Kroku 6.
- `exit=124` (zawieszenie) lub brak `0x3c` → idź do Kroku 4.

### Krok 4 — sprzęt: panel trzyma SDA (najczęstsza przyczyna)

1. **Odłącz zasilanie panelu**: wyjmij przewód VCC z pinu **4 (5 V)** na ok. 5 s
   i wsuń z powrotem. To resetuje SSD1306 i puszcza linię SDA.
   GND (pin 6) zostaw podłączony.
2. **Przepnij przewody** SDA (pin 3) i SCL (pin 5) — poluzowany styk daje
   dokładnie taki objaw. Sprawdź solidność GND (pin 6) i 5 V (pin 4).
3. Wymień przewody, jeśli są cienkie/„wiotkie”.
4. Powtórz Krok 3.

### Krok 5 — detekcja bez sterownika (bit-bang) i odblokowanie szyny

`oled_i2c_probe.py` używa GPIO przez sysfs, więc **musi mieć wolne piny**
(obecnie zajęte przez `i2c1`) — najpierw odłącz kontroler:

```
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/unbind
python3 /var/www/oled/oled_i2c_probe.py --scan      # skan 0x03..0x77
python3 /var/www/oled/oled_i2c_probe.py             # tylko 0x3c
python3 /var/www/oled/oled_i2c_probe.py --delay 50  # wolniejszy zegar
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind
```

Interpretacja wyniku:

| Komunikat | Znaczenie / działanie |
|---|---|
| `ACK from 0x3c - display detected` | sprzęt OK, wróć do Kroku 6 |
| `device found at 0x3d` | panel ma inny adres → użyj `--address 0x3d` |
| `no ACK from 0x3c ...` | problem sprzętowy (VCC/GND/przewody/modul) |
| `cannot export GPIO 227 (line in use?)` | nie odłączyłeś kontrolera (patrz wyżej) |

Sam `--scan` generuje impulsy zegara na SCL — przy wielu modułach „domyka” to
wiszącą transakcję i odblokowuje SDA. To najprostsze recovery bez restartu.

### Krok 6 — uruchom usługę i zweryfikuj

```
systemctl start oled-test
sleep 3
systemctl status oled-test --no-pager | head -12
journalctl -u oled-test -n 20 --no-pager
```

Na szkle powinny być 3 linie: nazwa płytki, data/godzina, `CPU xx.x C`.
**Jeśli podgląd PNG na stronie aktualizuje się, a ekran nadal jest czarny —
panel nie przyjmuje danych** → powtórz Krok 4/5.

Uwaga: po starcie usługi szynę zajmuje `python3`, więc `i2cdetect` może znowu
zawisnąć. Testuj `i2cdetect` **tylko przy zatrzymanej usłudze**.

### Krok 7 — restart systemu (usuwa procesy w stanie D)

```
reboot
```

Po starcie:

```
timeout 5 i2cdetect -y 1 ; echo "exit=$?"     # oczekiwane: 3c, exit=0
systemctl status oled-test --no-pager | head -12
```

Restart to najpewniejszy sposób skasowania zawieszonych `i2cdetect`
i zresetowania kontrolera `mv64xxx`.

### Krok 8 — panel odpowiada, ale obraz jest niepoprawny

| Objaw | Poprawka |
|---|---|
| Panel świeci na biało / tylko śmieci | `--driver sh1106` (część modułów 128x32 to SH1106) |
| Brak `0x3c`, ale `--scan` widzi `0x3d` | `--address 0x3d` |
| Tylko górna połowa obrazu (moduł 0.96") | `--height 64` |
| Obraz przesunięty / „urwany” | `--driver sh1106`, sprawdź `--height` |

Argumenty podaje się w `ExecStart` usługi
(`/etc/systemd/system/oled-test.service`), np.:

```
ExecStart=/usr/bin/python3 /var/www/oled/oled_test.py --interval 1 \
  --driver ssd1306 --height 32 \
  --status-json /var/www/oled/oled-status.json \
  --frame-png /var/www/oled/oled-frame.png
```

Po zmianie: `systemctl daemon-reload && systemctl restart oled-test`.

## 6. Zasady zapobiegawcze (BARDZO WAŻNE — przed każdym testem)

1. **Jeden proces na raz.** Przed uruchomieniem dowolnego skryptu testowego:
   ```
   systemctl stop oled-test
   ```
   Usługa bez przerwy trzyma `/dev/i2c-1`; równoległy dostęp = zablokowana szyna
   (dokładnie to się stało 2026-09-19 o 07:20).
2. **Nie używaj `oled_raw_i2c.py`** (bloki 512 B + własna inicjalizacja) — to on
   najprawdopodobniej zatrzasnął magistralę. Do testów używaj `luma`:
   `oled_white.py`, `oled_white_screen.py`, `oled_diag.py`.
3. **Zawsze opakowuj `i2cdetect` w `timeout`**:
   ```
   timeout 5 i2cdetect -y 1
   ```
   Bez tego proces zawiesi się w stanie `D` i będzie trzymał szynę do restartu.
4. Po skryptach GPIO/sysfs (`oled_i2c_probe.py`) **zawsze przywróć kontroler**:
   ```
   echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind
   ```
5. Po każdej sesji diagnostycznej sprawdź stan szyny:
   ```
   dmesg | grep -c 'bus locked'
   ps -o pid,stat,wchan:30,cmd -C i2cdetect
   fuser -v /dev/i2c-1
   ```
6. Nie usuwaj plików diagnostycznych „na siłę” — pomagają ustalić, co
   zatrzasnęło szynę (patrz sekcja 4).

## 7. Okablowanie (bez zmian)

| OLED | Złącze | SoC / linia | sysfs GPIO | Uwaga |
|------|--------|-------------|------------|-------|
| VCC  | pin 4  | 5 V         | —          | moduł ma własny LDO 3.3 V (662K) |
| GND  | pin 6  | GND         | —          | |
| SDA  | pin 3  | PH3         | 227        | TWI1-SDA |
| SCL  | pin 5  | PH2         | 226        | TWI1-SCK |

**Uwaga:** piny 3/5 na Orange Pi Win to **I2C1 (TWI1)**, nie I2C0.
Overlay `i2c0` (PH0/PH1) nie jest wyprowadzony na to złącze i nie zadziała.

Zasilanie całej płytki: pin 2 (5 V) i pin 6 (GND) — gniazdo DC jest uszkodzone.
Nie używamy pinu 1 (3.3 V), żeby nie blokować AXP803.

## 8. Włączanie magistrali (ZAKTUALIZOWANE — stan faktyczny tej maszyny)

`armbianEnv.txt` leży na partycji rozruchowej **`/dev/sda1`**, montowanej
w **`/boot`** (dodatkowo `/media/boot-media`) — **nie** `/dev/mmcblk0p1`
i nie `/mnt/bootpart`:

```
cat /boot/armbianEnv.txt        # oczekiwane: overlays=i2c1
```

Odtworzenie (jeśli kiedyś trzeba):

```
cp /boot/armbianEnv.txt /boot/armbianEnv.txt.bak
sed -i 's/^overlays=.*/overlays=i2c1/' /boot/armbianEnv.txt
sync && reboot
```

Weryfikacja po restarcie:

```
i2cdetect -l                       # mv64xxx_i2c adapter -> /dev/i2c-1
timeout 5 i2cdetect -y 1           # 0x3c w tabeli (PAMIĘTAJ o timeout)
```

Rollback: ustaw `overlays=` (pusto) i przywróć kopię:
`cp /boot/armbianEnv.txt.bak /boot/armbianEnv.txt`.

Overlay: `/boot/dtb/allwinner/overlay/sun50i-a64-i2c1.dtbo` (496 B).
Dla porównania dostępne są też `sun50i-a64-i2c0.dtbo` i warianty `h5`/`h6`
— **ich nie używaj**, na tym złączu działa wyłącznie `i2c1`.

## 9. Architektura aplikacji (stan po rozbudowie z 2026-09-18/19)

`oled_test.py` to **jeden proces = usługa systemd**, który:

1. w wątku `oled_loop` renderuje obraz 128x32 i wysyła klatki na panel
   (`device.display`),
2. wystawia REST API (Flask) na porcie **5003** (`app.run(host="0.0.0.0", port=5003)`),
3. zapisuje `oled-status.json` + `oled-frame.png` dla strony `/oled/`,
4. w razie błędu I2C **loguje go i leci dalej** — usługa się nie wywala
   (dlatego `status` może być „online”, choć panel jest martwy).

Sterowanie treścią odbywa się przez **stan** (`DisplayState`), a nie sztywną pętlę:

- `mode`: `SYSTEM_DEFAULT` | `CUSTOM` | `IMAGE` | `SCROLL_H` | `DIAGNOSTICS`
- `render_mode`: `None` | `"max"` | `"scroll_h"` (poziomy przewijany tekst)
- `current_rows`: lista linii do wyświetlenia
- `history`: max **20** wpisów `{id, timestamp, rows, mode}` (nowe na początku)
- `diagnostic_mode`: `fill_max` | `border` | `grid` | `checkerboard` | `text_demo`

nginx proxuje `/api/` → `127.0.0.1:5003/api/`
(`/etc/nginx/sites-available/default`, sekcja „Przekierowanie API OLED”).
Dzięki temu frontend woła `/api/...` bez znajomości portu.

## 10. API (faktyczne endpointy w kodzie)

| Metoda | Ścieżka | Wejście | Działanie |
|---|---|---|---|
| GET | `/api/status` | — | bieżący stan: `rows`, `mode`, `renderMode`, `cpuTemp`, `uptime`, `pid`, `updated` |
| POST | `/api/command` | `{"input":"...","lines_count":"auto"\|1\|2\|3\|"max"}` | parser komend i dowolnego tekstu |
| GET | `/api/history` | — | `{"history":[...]}` (max 20 wpisów) |
| POST | `/api/history/restore/<id>` | — | ponowne wysłanie wpisu z historii (`id` z `/api/history`) |
| POST | `/api/upload-image` | obraz (multipart) | tryb `IMAGE` — obraz 1-bit na panelu |

> **Uwaga na rozbieżność nazw:** pierwotne wymagania mówiły o `/api/display/text`,
> `/api/display/default`, `/api/display/history`, `/api/display/restore/{id}`,
> `/api/agent/command`. W kodzie zrealizowano to jako powyższy zestaw
> (`/api/command` łączy „text + agent”). Jeśli frontend (albo inny skrypt)
> woła stary `/api/display/*`, trzeba go dopasować do tych ścieżek.

Przykłady (działają lokalnie, bez nginx):

```
curl -s http://127.0.0.1:5003/api/status | python3 -m json.tool

curl -s -X POST http://127.0.0.1:5003/api/command \
     -H 'Content-Type: application/json' \
     -d '{"input":"temp"}'

curl -s -X POST http://127.0.0.1:5003/api/command \
     -H 'Content-Type: application/json' \
     -d '{"input":"Alarm: piec 72C","lines_count":"auto"}'

curl -s -X POST http://127.0.0.1:5003/api/command \
     -H 'Content-Type: application/json' \
     -d '{"input":"reset"}'

curl -s http://127.0.0.1:5003/api/history | python3 -m json.tool

curl -s -X POST http://127.0.0.1:5003/api/history/restore/abc12345

# przez nginx (jak z przeglądarki):
curl -s http://127.0.0.1/api/status
```

## 11. Komendy rozpoznawane przez parser (`format_custom_text`)

| Wpis użytkownika | Efekt na ekranie |
|---|---|
| `domyslny`, `reset`, `system`, `default` | powrót do `SYSTEM_DEFAULT` (pulpit: nazwa / data-godzina / CPU) |
| `temp`, `temperatura`, `cpu` | `[nazwa, CPU xx.x C, uptime]` |
| `zegar`, `czas`, `time`, `clock` | `[data, godzina, nazwa]` |
| `fill_max`, `maksymalne`, `wypelnij`, `all_pixels` | tryb `DIAGNOSTICS` — pełne wypełnienie 128x32 |
| `demo`, `demonstracja` | sekwencja: border → grid → checkerboard → fill_max → text_demo |
| dowolny inny tekst | `CUSTOM` — zawijanie do max 3 linii × 18 znaków |

Zawijanie: `wrap_text(text, max_chars=18, max_lines=3)` — tnie po słowach,
długie pojedyncze słowa dzieli twardo co 18 znaków. Limit wejścia: 120 znaków.

Rozmiary czcionek (`get_font_size_for_lines`, panel 32 px):
`1 linia → 70% wysokości`, `2 linie → 42%`, `3 linie → 28%`.
Tryb `"max"` (`lines_count`) wyświetla tekst jako **jedną dużą linię**
(z przewijaniem poziomym, gdy szerszy niż panel).

## 12. Pliki projektu

| Plik | Rola | Uwaga |
|---|---|---|
| `oled_test.py` | serwis: pętla OLED + Flask API (5003) + historia + parser komend | 777 linii, `main()` startuje wątek + `app.run` |
| `oled-status.json` | stan dla strony `/oled/` (na żywo) | zawiera `mode`, `renderMode`, `rows`, `cpuTemp` |
| `oled-frame.png` | zrzut klatki 128x32 dla podglądu | zapisywany nawet przy martwym panelu |
| `index.html` + `app.js` | strona `/oled/` (ciemny motyw, dioda online) | — |
| `oled_i2c_probe.py` | ratunkowy bit-bang I2C (sysfs GPIO, `--scan`) | wymaga odłączonego kontrolera `i2c1` |
| `oled_white.py` | test białego ekranu (luma) | **wymaga `systemctl stop oled-test`** |
| `oled_white_screen.py` | najprostszy test białego ekranu (luma) | idem |
| `oled_diag.py` | test: biały → kontrast → wzór → clear (luma) | idem |
| `oled_diag2.py` | test z logowaniem kroków i 10 s pauzą (luma) | idem |
| `oled_raw_i2c.py` | **NIEBEZPIECZNY** — surowe bloki 512 B, patrz sekcja 6 pkt 2 | nie używać |
| `README-oled.md` | ten plik (pełna instrukcja + dziennik naprawy) | |
| `README-oled.md.bak-20260919` | kopia poprzedniej wersji README | 2928 B |
| `/usr/local/sbin/oled-recover` | skrypt ratunkowy (stop → unbind/bind → test → start) | sekcja 15.5, `chmod 755` |

## 13. Rozwiązywanie problemów — szybka tabela

| Objaw | Sprawdź | Napraw |
|---|---|---|
| Ekran czarny, usługa działa | `dmesg \| grep 'bus locked'` | **`oled-recover`** (sekcja 15.5) lub sekcja 5, Kroki 1–3 |
| `i2cdetect` wisi / nie kończy się | `ps -o pid,stat,wchan,cmd -C i2cdetect` | `pkill -9 i2cdetect`, Krok 2 lub reboot |
| Brak `/dev/i2c-1` | `overlays=i2c1`, `.dtbo`, `pinmux-pins` | sekcja 8 |
| Magistrala jest, brak `0x3c` | `timeout 5 i2cdetect -y 1` | Krok 4 (zasilanie/przewody) |
| Sprzęt OK, ale brak `0x3c` w sterowniku | `oled_i2c_probe.py --scan` | Krok 5 |
| Panel świeci na biało / śmieci | — | `--driver sh1106`, ew. `--height` |
| Podgląd PNG się zmienia, ekran nie | `journalctl -u oled-test` (szukaj `I2C write error`) | Krok 4/5 — panel nie przyjmuje danych |
| Podgląd PNG stoi w miejscu, API odpowiada pustką (timeout), NLWP rośnie | `stat -c '%y' oled-frame.png` ×2 (sleep 5), `ps -o nlwp -C python3` | **`systemctl restart oled-test`** (sekcja 15.7) — NIE ruszaj I2C |
| `cannot export GPIO ... (line in use?)` | `cat .../pinmux-pins` | odłącz kontroler przed bit-bangiem |
| Usługa nie wstaje | `journalctl -u oled-test -n 50` | sprawdź `python3 -c "import flask"` (apt `python3-flask`) |

## 14. Tło historyczne / informacje NIEAKTUALNE

Poniższe zapisy z wcześniejszej wersji tego README **nie odpowiadają już
rzeczywistości** — zostawione, by uniknąć pomyłek przy kopiowaniu starych komend:

- ~~`armbianEnv.txt` leży na `/dev/mmcblk0p1` w katalogu `/mnt/bootpart`~~ →
  prawidłowo: **`/dev/sda1`, `/boot/armbianEnv.txt`**.
- ~~`oled_test.py` tylko wyświetla 3 linie, bez API~~ →
  teraz: **Flask na porcie 5003 + historia + parser komend + tryby
  (CUSTOM/IMAGE/SCROLL_H/DIAGNOSTICS)**.
- ~~`mount -o remount,rw /mnt/bootpart`~~ → katalog `/mnt/bootpart` **nie istnieje**;
  partycja jest zamontowana w `/boot` jako `rw` (patrz `findmnt /boot`).
- ~~`systemctl disable --now oled-test` do testów~~ → do testów wystarczy
  `systemctl stop oled-test`, ale **dostępu do I2C nie ma współdzielonego —
  jeden proces na raz**.
- ~~strona `/oled/` „pokazuje dokładnie to, co jest na ekranie”~~ → **nie**,
  gdy I2C jest zablokowane: pliki są generowane z renderu, nie z panelu.

## 15. Dziennik naprawy — pełny zapis sesji (2026-09-19)

### 15.1 Oś czasu

| Czas (CEST) | Zdarzenie |
|---|---|
| 2026-09-18 21:49 | start systemu (uptime 0) |
| 07:16–07:21 | powstają skrypty diagnostyczne: `oled_white_screen.py`, `oled_diag.py`, `oled_raw_i2c.py`, `oled_white.py`, `oled_diag2.py` |
| ~07:20 (uptime 34227 s) | **pierwszy** wpis `mv64xxx: I2C bus locked` → wyświetlacz przestaje działać |
| 07:29–07:33 | diagnoza: `i2cdetect` zawiesza się (`exit=124`), 2× `i2cdetect` w stanie `D`, pinmux i overlay OK |
| 07:33 | licznik `bus locked` = **347**, ostatni wpis przy uptime 35253 |
| 07:43 | licznik = **350** — blokada trwa nieprzerwanie |
| 07:47:55 | `systemctl stop oled-test` → `inactive`; zawieszone `i2cdetect` znikają |
| 07:48 | test `timeout 6 i2cdetect -y 1` → nadal `exit=124` (blokada **nie** puszcza sama) |
| 07:49 | **unbind/bind kontrolera `1c2b000.i2c`** → `/dev/i2c-1` wraca, `i2cdetect` pokazuje **`3c`, exit=0** |
| 07:49 | test `oled_white_screen.py` → `White screen displayed` (panel zamigotał na biało) |
| 07:50:53 | `systemctl start oled-test` → `active (running)`, PID 35089 |
| 07:50:56 | log: `OLED: OrangePi Win on bus 1, address 0x3c, panel 128x32, driver ssd1306, refresh 1.00s` |
| 07:51–07:53 | weryfikacja: 0× `I2C write error`, przerwania I2C rosną, API `temp` i `reset` działają |
| 07:52 | **STATUS: NAPRAWIONE** — ekran pokazuje pulpit systemowy |

### 15.2 Dokładne wyniki (przed → po)

**PRZED (07:33) — magistrala zatrzaśnięta:**

```
$ timeout 8 i2cdetect -y 1 ; echo "exit=$?"
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- exit=124

$ ps -o pid,stat,wchan:30,cmd -C i2cdetect
    PID STAT WCHAN                          CMD
  30420 D+   rt_mutex_schedule              i2cdetect -y 1
  30686 D+   mv64xxx_i2c_wait_for_completio i2cdetect -y 1

$ dmesg | grep -c 'bus locked'
347
```

**PO (07:49–07:53) — magistrala działa:**

```
$ timeout 6 i2cdetect -y 1 ; echo "exit=$?"
30: -- -- -- -- -- -- -- -- -- -- -- -- 3c -- -- --
exit=0

$ ps -o pid,stat,cmd -C i2cdetect        # pusty wynik
$ dmesg | grep -c 'bus locked'
350                                      # i NIE rośnie

$ grep mv64xxx /proc/interrupts          # dwa odczyty w odstępie 2 s
161:   10257903          0          0          0    GICv2  39 Level     mv64xxx_i2c
161:   10258427          0          0          0    GICv2  39 Level     mv64xxx_i2c
                                         # +524 przerwań = realny ruch I2C na panel
```

### 15.3 Sprawdzone i WYKLUCZONE (żeby nie szukać po omacku)

| Hipoteza | Weryfikacja | Werdykt |
|---|---|---|
| Zły device tree / brak overlaya | `/boot/armbianEnv.txt` = `overlays=i2c1`; `sun50i-a64-i2c1.dtbo` istnieje (496 B) | ❌ wykluczone |
| Zły pinmux | `pinmux-pins`: PH2/PH3 = `function i2c1`, kontroler `1c2b000.i2c` | ❌ wykluczone |
| Brak bibliotek | `luma.oled 3.10.0`, `luma.core 2.4.2`, `Pillow 11.1.0`, `smbus2 0.4.3` | ❌ wykluczone |
| Brak Flask / brak API | Flask 3.1.1 (apt `python3-flask`) + Werkzeug 3.1.3, API zwraca `200` | ❌ wykluczone |
| Zły adres panelu | po naprawie panel ACK-uje na `0x3c` | ❌ wykluczone |
| Uprawnienia do `/dev/i2c-1` | `root`, urządzenie `crw-rw---- root i2c` | ❌ wykluczone |
| Błąd kodu `oled_test.py` | brak błędów w logu, API i render działają | ❌ wykluczone |
| **Zatrzaśnięta magistrala I2C1** | `bus locked` × 350 + procesy w stanie `D`; **naprawa unbind/bind pomogła** | ✅ **PRZYCZYNA** |

### 15.4 Trwałość naprawy

- Unbind/bind resetuje **kontroler** w pamięci — nie zmienia nic w plikach
  systemowych ani w device tree, więc **nic nie trzeba „utrwalać”**.
- Po restarcie systemu magistrala i tak inicjalizuje się od zera — stan
  „bus locked” nie wraca samoistnie.
- Problem wróci **tylko** po ponownym przerwaniu transmisji (np. równoległe
  skrypty przy działającej usłudze). Wtedy powtórz sekcję 15.5 / sekcję 5.
### 15.5 Skrypt naprawczy (gotowy do użycia)

Zapisz jako `/usr/local/sbin/oled-recover`, nadaj prawa wykonywania
(`chmod 755`) i uruchom `oled-recover` — robi dokładnie to, co zadziałało
w tej sesji:

```bash
#!/bin/bash
# oled-recover — ratunek dla zatrzaśniętej magistrali I2C1 (Orange Pi Win)
set -u
DRV=/sys/bus/platform/drivers/mv64xxx_i2c
DEV=1c2b000.i2c

echo "[1/5] zatrzymuję usługę…"
systemctl stop oled-test
sleep 1

echo "[2/5] usuwam zawieszone procesy…"
pkill -9 i2cdetect 2>/dev/null || true
sleep 1

echo "[3/5] reset kontrolera I2C ($DEV)…"
echo "$DEV" > "$DRV/unbind"; sleep 2
echo "$DEV" > "$DRV/bind";   sleep 3

echo "[4/5] test magistrali…"
if timeout 6 i2cdetect -y 1 | grep -q ' 3c '; then
    echo "     OK — panel widoczny na 0x3c"
else
    echo "     BŁĄD — panel nie odpowiada."
    echo "     -> odłącz VCC (pin 4) na 5 s, przepnij SDA (pin 3) / SCL (pin 5)"
    echo "     -> potem powtórz:  oled-recover"
    exit 2
fi

echo "[5/5] startuję usługę…"
systemctl start oled-test
sleep 4
echo -n "usługa:   "; systemctl is-active oled-test
echo -n "blokady:  "; dmesg | grep -c 'bus locked'
```

### 15.6 Stan końcowy po naprawie (2026-09-19 07:53 CEST)

| Element | Wartość |
|---|---|
| Usługa | `active (running)`, PID **35089**, `NRestarts=0` |
| Licznik `bus locked` | **350** — zatrzymany, nie rośnie |
| Ruch I2C | licznik `mv64xxx_i2c` w `/proc/interrupts` rośnie (~260/s) |
| Ekran | `OrangePi Win` / `2026-09-19 07:53:00` / `CPU 58.5 C` |
| Tryb | `SYSTEM_DEFAULT` (`renderMode: null`) |
| API | `GET /api/status` ✔ · `POST /api/command` ✔ · `GET /api/history` ✔ |
| Błędy zapisu | `0` wystąpień `I2C write error` |

**Jeśli kiedyś objaw wróci:** nie szukaj błędu w kodzie ani w device tree —
uruchom `oled-recover` i sprawdź, czy `i2cdetect` widzi `3c`.

### 15.7 Incydent 2 (2026-09-19 08:11 CEST) — cichy deadlock usługi (userspace)

**Objawy (zaobserwowane 08:08–08:10):**

- `oled-frame.png` miał mtime **07:57:04** i nie zmieniał się przez 20 s — zegar na
  ekranie stał w miejscu, ale panel **nadal coś pokazywał** (SSD1306 trzyma ostatnią
  klatkę) → wyglądało, że „wszystko działa”,
- `GET /api/status`, `GET /api/history`, `POST /api/command` odpowiadały **pustką**
  (curl zrywał po timeoutie, w dzienniku brak wpisu o żądaniu — Flask loguje po
  zakończeniu handlera, a handler wisiał),
- serwer odpowiadał jedynie `404` dla `/` i `/favicon.ico` (ścieżki bez wspólnego locka),
- proces żył (`active`), ale **NLWP=193** (każde żądanie dokładało zawieszony wątek)
  przy normie ~6,
- **zero** nowych wpisów `I2C bus locked` (licznik stał na 350), zero `I2C write error`,
- w dzienniku **brak Tracebacka** — zawieszenie było całkowicie ciche.

**Wniosek (root cause):** deadlock w userspace — najpewniej wyścig między pętlą
renderującą a handlerami API współdzielącymi stan klatki. **To NIE była magistrala
I2C**: jądro nie zgłaszało zawieszonej transakcji, a licznik przerwań stał, bo pętla
renderująca przestała zapisywać. Zatrzaśnięta szyna (incydent 1) to zupełnie inny obraz.

**Naprawa:** wystarczył zwykły restart — **bez** `unbind`/`bind`:

```
systemctl restart oled-test
```

**Weryfikacja po resecie (08:11:41, nowy PID 39588):**

| Wskaźnik | Przed (zamarznięty) | Po restarcie |
|---|---|---|
| Klatka PNG | mtime stały od 07:57:04 | odświeżana co 1 s (08:11:52 → 08:12:02) |
| Przerwania `mv64xxx_i2c` /10 s | **0** | **+2 620** (~262/s, normalne) |
| `/api/status` | pusta odpowiedź (timeout) | pełny JSON: `SYSTEM_DEFAULT`, CPU 59.5 °C |
| Wątki procesu (NLWP) | **193** | **6** |
| `bus locked` (dmesg) | 350 — bez zmian | 350 — bez zmian |
| Błędy I2C w logu | 0 | 0 |

**Jak szybko odróżnić ten incydent od zatrzaśniętej szyny:**

| Badanie | Deadlock usługi (15.7) | Zatrzaśnięta szyna (incydent 1) |
|---|---|---|
| `dmesg \| grep -c 'bus locked'` | stoi w miejscu | rośnie (351, 352…) |
| `timeout 5 i2cdetect -y 1` | `exit=0`, widzi `3c` | `exit=124` (wisi) |
| mtime `oled-frame.png` ×2 (sleep 5) | **stały** | zwykle się zmienia (render działa, zapis nie) |
| `ps -o nlwp -C python3` (usługa) | rośnie (100+) | normalne (~6) |
| Napraw | `systemctl restart oled-test` | `oled-recover` / unbind+bind |

**Rekomendacja (ochrona przed powtórką):** upewnij się, że w `[Service]` jest
`Restart=always` + `RestartSec=3`, i dodaj najprostszy strażnik (usługa odświeża
PNG co 1 s, więc klatka starsza niż minutę = zawieszenie):

```
# crontab -e  (root)
* * * * * find /var/www/oled/oled-frame.png -mmin -1 | grep -q . || systemctl restart oled-test
```

### 15.8 Incydent 3 (2026-09-19, ok. 09:09 CEST) — czarne szkło przy zdrowej szynie

**Objaw:** ekran nic nie pokazywał, choć wszystko inne było zdrowe: usługa
`active`, PNG i `oled-status.json` odświeżane co 1 s, API 200 (bezpośrednio i
przez nginx), `dmesg | grep -c 'bus locked'` = **0**, brak procesów w stanie `D`,
przerwania `mv64xxx_i2c` rosły ~350/s (ruch I2C płynął).

**Diagnoza (dowody):**

```
journalctl -u oled-test --since '08:49:50' | grep 'I2C write error' | head -3
→ I2C write error: [Errno 11] Resource temporarily unavailable
  (co 2 s, od 08:52:23 do 08:53:01)

dmesg | grep 'Ctlr Error'
→ [ 233.063199] i2c i2c-1: mv64xxx_i2c_fsm: Ctlr Error -- state: 0x6,
  status: 0x38, addr: 0x3c, flags: 0x200
  (uptime 233–255 s = 08:52:39–08:53:01; reboot był o 08:48:46 →
  status 0x38 = arbitration lost, panel niestabilny tuż po zimnym starcie)
```

**Przyczyna (root cause):** wyścig po zimnym starcie — system wystartował
o 08:48:46, usługa o 08:49:53, ale przez ~3,5 min panel (LDO 662K) gubił arbiter
na I2C. Klatki w tym oknie były odrzucane, a **sekwencja init panelu nie została
przyjęta**. `oled_test.py` inicjalizował urządzenie **tylko raz** przy starcie i
po błędach zapisu leciał dalej bez re-initu — klatki bez initu nie ożywiają szkła
(SSD1306 po resecie: display OFF, charge pump OFF). Stąd czarny ekran mimo
sprawnego API i ruchu na szynie. (Bonus: `run_demo()` miał NameError na `args`.)

**Naprawa doraźna (09:11:32):** `systemctl restart oled-test` przy zdrowej szynie
→ świeża sekwencja init → obraz wrócił. Kontrola: `i2cdetect -y 1` przy
zatrzymanej usłudze → `3c`, `exit=0`; po starcie **0** błędów I2C w journal.

**Naprawa trwała (wdrożona 09:20–09:25):**

1. **`oled_test.py` — auto re-init (self-heal):**
   - jeśli init przy starcie się nie powiedzie (tryb offline / DummyDevice),
     pętla renderująca co 30 s próbuje zbudować urządzenie ponownie,
   - po **≥5 kolejnych** błędach zapisu pętla odbudowuje urządzenie
     (`build_device()`) i wysyła init od nowa; cooldown 30 s,
   - komunikaty w journal: `OLED re-init: real device attached…`,
     `OLED re-init: device recreated…`, `I2C recovered after N failed write(s)`,
     `OLED re-init attempt failed… (will retry in 30s)`,
   - przetestowane offline: uruchomienie z `--bus 9` → init pada, re-init
     ponawiany co 30 s ✔ (log: 2× `OLED re-init attempt failed`).
2. **`run_demo()`:** naprawiony NameError (`args = state.args`).
3. **`oled-test.service`:** `Restart=always` + **`RestartSec=3`** (było 10).
4. **Strażnik w crontabie roota** (zainstalowany 09:23, wariant z 15.7
   zabezpieczony `is-active`, żeby nie odpalał usługi podczas celowego
   `systemctl stop`, np. w trakcie `oled-recover`):
   ```
   * * * * * systemctl is-active --quiet oled-test && ! find /var/www/oled/oled-frame.png -mmin -1 | grep -q . && systemctl restart oled-test
   ```

**Jak rozpoznać incydent 3 (szkło czarne, szyna zdrowa):**

| Badanie | Wynik |
|---|---|
| `dmesg \| grep -c 'bus locked'` | stoi (0 lub bez zmian) |
| `stat -c '%y' oled-frame.png` ×2 (sleep 3) | zmienia się co 1 s |
| `curl http://127.0.0.1:5003/api/status` | HTTP 200, JSON świeży |
| `journalctl -u oled-test \| grep 'I2C write error'` | zwykle seria błędów zaraz po starcie |
| Napraw | `systemctl restart oled-test`; od 09:25 auto re-init robi to samo sam |

**Zasada:** czarne szkło + zdrowa szyna = problem z **brakiem initu** panelu, nie z magistralą.
Restart usługi wysyła init ponownie; od wdrożenia auto re-init panel ożywia się sam.

---

---

**Skrót dla naprawiającego (TL;DR):**

```
systemctl stop oled-test
pkill -9 i2cdetect
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/unbind
sleep 2
echo 1c2b000.i2c > /sys/bus/platform/drivers/mv64xxx_i2c/bind
timeout 5 i2cdetect -y 1 ; echo "exit=$?"      # ma pokazać 3c i exit=0
# jeśli nadal exit=124 -> odłącz VCC (pin 4) na 5 s, przepnij SDA/SCL, powtórz
systemctl start oled-test

# CZARNE SZKŁO, ale szyna ZDROWA (bus locked = 0, PNG/API świeże, 3c widoczne):
#   systemctl restart oled-test        # ponowny init panelu (incydent 3 — sekcja 15.8)
#   od 09:25 panel inicjalizuje się też sam (auto re-init w oled_test.py)
```

Diagnozę wykonano: **2026-09-19 07:33 CEST**.
Naprawę wykonano i zweryfikowano: **2026-09-19 07:52 CEST** (sekcja 15).
Incydent 2 (cichy deadlock usługi) usunięto restartem: **2026-09-19 08:11 CEST** (sekcja 15.7).
Incydent 3 (czarne szkło przy zdrowej szynie) naprawiono restartem i utrwalono
auto re-init + `RestartSec=3` + strażnika w cronie: **2026-09-19 09:25 CEST** (sekcja 15.8).
System: **Armbian 26.11.0-trunk.51 trixie**, kernel **6.18.51-current-sunxi64**,
Orange Pi Win, panel **SSD1306 128x32 @ 0x3c** na magistrali **/dev/i2c-1**.

> **Podsumowanie jednym zdaniem:** wyświetlacz był martwy z powodu zatrzaśniętej
> magistrali I2C1 (`mv64xxx: I2C bus locked`); pomogło zatrzymanie usługi
> `oled-test` i reset kontrolera przez `unbind`/`bind` urządzenia `1c2b000.i2c`.
> Panel działa, a kluczowa zasada to: **przed każdym testem zatrzymaj usługę
> (`systemctl stop oled-test`) i nigdy nie używaj `oled_raw_i2c.py`.**
