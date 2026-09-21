#!/usr/bin/env python3
"""Status display and interactive web backend for Orange Pi Win on an I2C OLED.
Supports SSD1306 and SH1106 (common in 128x32 modules)."""
import argparse
import glob
import json
import os
import socket
import sys
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, jsonify, request
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306, sh1106
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:  # production WSGI server: bounded worker pool, no dev-server thread churn
    from waitress import serve as waitress_serve
except ImportError:  # fall back to the Flask development server
    waitress_serve = None

MODEL_PATH = "/proc/device-tree/model"
TEMP_PATH = "/sys/class/thermal/thermal_zone0/temp"
UPTIME_PATH = "/proc/uptime"

STATUS_JSON = "/var/www/oled/oled-status.json"
FRAME_PNG = "/var/www/oled/oled-frame.png"

FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)

DEFAULT_ADDRESS = 0x3C
FONT_CACHE = {}

app = Flask(__name__)

# Global state manager
class DisplayState:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "SYSTEM_DEFAULT"  # SYSTEM_DEFAULT, CUSTOM, IMAGE, SCROLL_H, DIAGNOSTICS
        self.current_rows = []
        self.lines_count_setting = "auto"
        self.render_mode = None  # None, "max", "scroll_h"
        self.custom_image = None  # PIL Image for IMAGE mode
        self.custom_image_filename = ""  # Filename for IMAGE mode
        self.diagnostic_mode = None  # "fill_max", "border", "grid", "checkerboard", "text_demo"
        self.scroll_offset = 0  # Current X offset for SCROLL_H
        self.scroll_pause_until = 0  # Timestamp for pause
        self.history = []  # Max 20 items
        self.device = None
        self.args = None
        self.last_status = {}

state = DisplayState()

def read_text(path, default=""):
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", "replace").strip("\x00 \n")
    except OSError:
        return default

def board_name():
    model = read_text(MODEL_PATH)
    if not model:
        return socket.gethostname()
    return model.split("/")[0].strip()

def cpu_temperature():
    try:
        with open(TEMP_PATH) as handle:
            return int(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None

def uptime_text():
    try:
        with open(UPTIME_PATH) as handle:
            seconds = int(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return ""
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%dd %02d:%02d" % (days, hours, minutes)
    return "%02d:%02d" % (hours, minutes)

def load_font(size):
    if size not in FONT_CACHE:
        font = None
        for path in FONT_PATHS:
            if os.path.isfile(path):
                font = ImageFont.truetype(path, size)
                break
        FONT_CACHE[size] = font or ImageFont.load_default(size=size)
    return FONT_CACHE[size]

def get_font_size_for_lines(num_lines, height):
    if num_lines == 1:
        return int(height * 0.70) if height <= 32 else int(height * 0.60)
    elif num_lines == 2:
        return int(height * 0.42) if height <= 32 else int(height * 0.35)
    else:
        return int(height * 0.28) if height <= 32 else int(height * 0.22)

def wrap_text(text, max_chars=18, max_lines=3):
    words = text.split()
    if not words:
        return [""]
    lines = []
    current_line = ""
    for word in words:
        if not current_line:
            if len(word) > max_chars:
                # Split long single word
                while word and len(lines) < max_lines:
                    lines.append(word[:max_chars])
                    word = word[max_chars:]
            else:
                current_line = word
        else:
            test_line = current_line + " " + word
            if len(test_line) <= max_chars:
                current_line = test_line
            else:
                lines.append(current_line)
                if len(lines) >= max_lines:
                    break
                if len(word) > max_chars:
                    while word and len(lines) < max_lines:
                        lines.append(word[:max_chars])
                        word = word[max_chars:]
                    current_line = ""
                else:
                    current_line = word
    if current_line and len(lines) < max_lines:
        lines.append(current_line)
    return lines[:max_lines] if lines else [""]

def format_custom_text(input_str, lines_count_setting, name, temp, uptime):
    text = input_str.strip()
    
    # Validate max length
    if len(text) > 120:
        text = text[:120]
    
    lower = text.lower()

    if lower in ("domyslny", "reset", "system", "default"):
        return "SYSTEM_DEFAULT", [], None

    if lower in ("temp", "temperatura", "cpu"):
        temp_str = "CPU --.- C" if temp is None else "CPU %.1f C" % temp
        return "CUSTOM", [name, temp_str, uptime or "uptime --"], None

    if lower in ("zegar", "czas", "time", "clock"):
        now = datetime.now()
        return "CUSTOM", [now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), name], None

    if str(lines_count_setting).lower() == "max":
        return "CUSTOM", [text], "max"

    if lines_count_setting in (1, "1"):
        # For 1 line, check if text fits without wrapping
        font = load_font(22)  # Approximate font size for 1 line
        bbox = font.getbbox(text)
        if bbox[2] - bbox[0] > 128:
            # Text too wide - enable scroll mode with full text
            return "CUSTOM", [text], "scroll_h"
        lines = wrap_text(text, max_chars=16, max_lines=1)
    elif lines_count_setting in (2, "2"):
        lines = wrap_text(text, max_chars=18, max_lines=2)
    elif lines_count_setting in (3, "3"):
        lines = wrap_text(text, max_chars=18, max_lines=3)
    else:
        if len(text) <= 16:
            lines = wrap_text(text, max_chars=16, max_lines=1)
        elif len(text) <= 32:
            lines = wrap_text(text, max_chars=18, max_lines=2)
        else:
            lines = wrap_text(text, max_chars=18, max_lines=3)

    return "CUSTOM", lines, None

def render_frame(device, rows, render_mode=None, scroll_x=0, diagnostic_mode=None):
    image = Image.new("1", (device.width, device.height), 0)
    draw = ImageDraw.Draw(image)

    if diagnostic_mode == "fill_max":
        draw.rectangle((0, 0, device.width - 1, device.height - 1), fill=1)
        return image, None

    if diagnostic_mode == "border":
        draw.rectangle((0, 0, device.width - 1, device.height - 1), outline=1, width=1)
        return image, None

    if diagnostic_mode == "grid":
        for x in range(0, device.width, 8):
            draw.line((x, 0, x, device.height - 1), fill=1)
        for y in range(0, device.height, 8):
            draw.line((0, y, device.width - 1, y), fill=1)
        return image, None

    if diagnostic_mode == "checkerboard":
        for y in range(device.height):
            for x in range(device.width):
                if ((x // 8) + (y // 8)) % 2 == 0:
                    draw.point((x, y), fill=1)
        return image, None

    if diagnostic_mode == "text_demo":
        text = "OLED DEMO"
        font = load_font(20)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (device.width - text_width) // 2
        y = (device.height - text_height) // 2
        draw.text((x, y), text, font=font, fill=1)
        return image, 20

    if render_mode == "max" and rows:
        text = rows[0]
        font = load_font(34)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_height = bbox[3] - bbox[1]
        text_width = bbox[2] - bbox[0]
        font_size = 34

        while (text_height > 32 or text_width > device.width) and font_size > 8:
            font_size -= 1
            font = load_font(font_size)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_height = bbox[3] - bbox[1]
            text_width = bbox[2] - bbox[0]

        if font_size <= 8:
            text = text[:18]

        y = max(0, -bbox[1])
        x = max(0, (device.width - text_width) // 2 - bbox[0])
        draw.text((x, y), text, font=font, fill=1)
        return image, font_size

    if render_mode == "scroll_h" and rows:
        text = rows[0]
        font = load_font(34)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_height = bbox[3] - bbox[1]
        text_width = bbox[2] - bbox[0]
        font_size = 34

        while (text_height > 32 or text_width > device.width) and font_size > 8:
            font_size -= 1
            font = load_font(font_size)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_height = bbox[3] - bbox[1]
            text_width = bbox[2] - bbox[0]

        if font_size <= 8:
            text = text[:18]

        y = max(0, -bbox[1])
        x = max(0, scroll_x - bbox[0])
        draw.text((x, y), text, font=font, fill=1)
        return image, font_size

    num_lines = max(1, len(rows))
    font_size = get_font_size_for_lines(num_lines, device.height)
    font = load_font(font_size)

    try:
        bbox = font.getbbox("Ay")
        line_height = (bbox[3] - bbox[1]) + 2
    except AttributeError:
        line_height = font_size + 2

    total_height = line_height * num_lines
    y = max(0, (device.height - total_height) // 2)

    for text in rows:
        draw.text((2, y), text, font=font, fill=1)
        y += line_height
    return image, font_size

def write_text_atomic(path, text):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = "%s.tmp" % path
        with open(tmp, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError as error:
        print("cannot write %s: %s" % (path, error), file=sys.stderr)

def write_image_atomic(path, image):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = "%s.tmp" % path
        image.save(tmp, format="PNG")
        os.replace(tmp, path)
    except OSError as error:
        print("cannot write %s: %s" % (path, error), file=sys.stderr)

def add_to_history(rows, mode):
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "mode": mode
    }
    state.history.insert(0, entry)
    if len(state.history) > 20:
        state.history = state.history[:20]

def run_demo(device):
    args = state.args  # naprawa: run_demo nie mial dostepu do args (NameError przy zapisie PNG)
    with state.lock:
        previous_mode = state.mode
        previous_render_mode = state.render_mode
        previous_rows = state.current_rows
        previous_diagnostic_mode = getattr(state, 'diagnostic_mode', None)
    
    try:
        demo_steps = [
            ("border", 1.0),
            ("grid", 1.0),
            ("checkerboard", 1.0),
            ("fill_max", 1.5),
            ("text_demo", 1.5),
        ]
        
        for diagnostic_mode, duration in demo_steps:
            with state.lock:
                state.mode = "DIAGNOSTICS"
                state.render_mode = None
                state.diagnostic_mode = diagnostic_mode
                state.current_rows = ["[Demo: %s]" % diagnostic_mode]
            
            start_time = time.time()
            while time.time() - start_time < duration:
                image, _ = render_frame(device, [], diagnostic_mode=diagnostic_mode)
                try:
                    if state.device: state.device.display(image)
                except Exception as i2c_err:
                    print("I2C write error in demo: %s" % i2c_err, file=sys.stderr)
                
                if args.frame_png:
                    write_image_atomic(args.frame_png, image)
                
                time.sleep(0.05)
    finally:
        with state.lock:
            state.mode = previous_mode
            state.render_mode = previous_render_mode
            state.current_rows = previous_rows
            state.diagnostic_mode = previous_diagnostic_mode

REINIT_ERROR_THRESHOLD = 5   # po tylu kolejnych bledach zapisu probuj przeinicjalizowac panel
REINIT_COOLDOWN = 30.0       # minimalny odstep miedzy probami re-init [s]

def oled_loop(device, args):
    name = board_name()
    frame_counter = 0
    consecutive_errors = 0
    last_reinit_attempt = 0.0
    # Initialised before the loop so that an exception raised early in an
    # iteration cannot cause a NameError below and silently kill this thread.
    mode = "SYSTEM_DEFAULT"
    render_mode = None
    while True:
        try:
            now = datetime.now()
            temp = cpu_temperature()
            up = uptime_text()

            with state.lock:
                mode = state.mode
                render_mode = state.render_mode
                custom_image = state.custom_image
                diagnostic_mode = getattr(state, 'diagnostic_mode', None)
                
                if mode == "SYSTEM_DEFAULT":
                    temp_str = "CPU --.- C" if temp is None else "CPU %.1f C" % temp
                    rows = [name, now.strftime("%Y-%m-%d %H:%M:%S"), temp_str]
                elif mode == "IMAGE" and custom_image:
                    rows = ["[Obraz: %s]" % state.custom_image_filename]
                elif mode == "DIAGNOSTICS":
                    rows = state.current_rows if state.current_rows else ["[Diagnostics]"]
                else:
                    rows = state.current_rows if state.current_rows else [name, "Custom Mode", now.strftime("%H:%M:%S")]

            # Handle IMAGE mode - display the uploaded image directly
            if mode == "IMAGE" and custom_image:
                image = custom_image.copy()
                frame_font_size = None
                time.sleep(max(0.05, args.interval))
            elif mode == "DIAGNOSTICS":
                image, frame_font_size = render_frame(device, rows, diagnostic_mode=diagnostic_mode)
                time.sleep(max(0.05, args.interval))
            else:
                # Handle SCROLL_H mode
                scroll_x = 0
                if render_mode == "scroll_h" and rows:
                    current_time = time.time()
                    
                    # Initialize scroll state if needed
                    if state.scroll_offset == 0 and state.scroll_pause_until == 0:
                        state.scroll_pause_until = current_time + 0.5  # Initial pause
                    
                    if current_time < state.scroll_pause_until:
                        # In pause period
                        scroll_x = 128 if state.scroll_offset == 0 else state.scroll_offset
                    else:
                        # Calculate text width for scroll
                        font = load_font(34)
                        bbox = font.getbbox(rows[0])
                        text_width = bbox[2] - bbox[0]
                        
                        if state.scroll_offset == 0:
                            # Starting scroll from right
                            state.scroll_offset = 128
                        
                        # Move scroll position
                        state.scroll_offset -= 3
                        
                        if state.scroll_offset < -text_width:
                            # Reached end, pause and reset
                            state.scroll_offset = 0
                            state.scroll_pause_until = current_time + 0.5
                            scroll_x = 128
                        else:
                            scroll_x = state.scroll_offset
                    
                    image, frame_font_size = render_frame(device, rows, render_mode="scroll_h", scroll_x=scroll_x)
                    time.sleep(0.04)  # ~25 FPS for scroll
                else:
                    image, frame_font_size = render_frame(device, rows, render_mode=render_mode)
                    time.sleep(max(0.05, args.interval))

            # Self-heal 1: init mogl nie wyjsc przy starcie (tryb offline) — probuj
            # zbudowac prawdziwe urzadzenie, az wyscig po zimnym starcie minie.
            if getattr(device, "is_dummy", False):
                now_ts = time.monotonic()
                if now_ts - last_reinit_attempt >= REINIT_COOLDOWN:
                    last_reinit_attempt = now_ts
                    try:
                        new_device = build_device(args)
                        release_device(device)
                        state.device = new_device
                        device = new_device
                        consecutive_errors = 0
                        print("OLED re-init: real device attached after offline mode",
                              file=sys.stderr)
                    except Exception as re_err:
                        print("OLED re-init attempt failed: %s (will retry in %.0fs)"
                              % (re_err, REINIT_COOLDOWN), file=sys.stderr)

            try:
                if state.device: state.device.display(image)
                if consecutive_errors >= REINIT_ERROR_THRESHOLD:
                    print("I2C recovered after %d failed write(s)" % consecutive_errors,
                          file=sys.stderr)
                consecutive_errors = 0
            except Exception as i2c_err:
                consecutive_errors += 1
                print("I2C write error: %s" % i2c_err, file=sys.stderr)
                # Self-heal 2: seria bledow zapisu czesto oznacza, ze panel zgubil
                # sekwencje init (np. przerwana transmisja). Przeinicjalizuj panel,
                # bo same klatki nie ozywiaja wyswietlacza bez initu.
                now_ts = time.monotonic()
                if (consecutive_errors >= REINIT_ERROR_THRESHOLD
                        and now_ts - last_reinit_attempt >= REINIT_COOLDOWN):
                    last_reinit_attempt = now_ts
                    try:
                        new_device = build_device(args)
                        release_device(device)
                        state.device = new_device
                        device = new_device
                        consecutive_errors = 0
                        print("OLED re-init: device recreated after %s" % i2c_err,
                              file=sys.stderr)
                    except Exception as re_err:
                        print("OLED re-init attempt failed: %s (will retry in %.0fs)"
                              % (re_err, REINIT_COOLDOWN), file=sys.stderr)

            font_sizes = [frame_font_size] * len(rows) if rows and frame_font_size else []

            status = {
                "board": name,
                "bus": args.bus,
                "address": "0x%02x" % args.address,
                "panel": "%dx%d" % (args.width, args.height),
                "interval": args.interval,
                "service": "oled-test.service",
                "rows": rows,
                "fontSizes": font_sizes,
                "cpuTemp": None if temp is None else round(temp, 1),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                "uptime": up,
                "mode": mode,
                "renderMode": render_mode,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "pid": os.getpid(),
            }
            state.last_status = status
            
            if args.status_json:
                write_text_atomic(args.status_json, json.dumps(status, indent=2) + "\n")
            
            # Throttle PNG writes for scroll mode (every 12 frames)
            if args.frame_png:
                frame_counter += 1
                if render_mode != "scroll_h" or frame_counter % 12 == 0:
                    write_image_atomic(args.frame_png, image)

        except Exception as e:
            print("Error in oled_loop: %s" % e, file=sys.stderr)

        if render_mode != "scroll_h":
            time.sleep(max(0.05, args.interval))

# Flask REST API endpoints
@app.route("/api/status", methods=["GET"])
def api_status():
    with state.lock:
        if state.last_status:
            return jsonify(state.last_status)
    # Fallback if loop hasn't run yet
    now = datetime.now()
    temp = cpu_temperature()
    return jsonify({
        "board": board_name(),
        "bus": state.args.bus if state.args else 1,
        "address": "0x3c",
        "panel": "128x32",
        "interval": 1.0,
        "service": "oled-test.service",
        "rows": [board_name(), now.strftime("%Y-%m-%d %H:%M:%S"), "CPU --.- C"],
        "fontSizes": [10, 10, 10],
        "cpuTemp": None if temp is None else round(temp, 1),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": uptime_text(),
        "mode": state.mode,
        "renderMode": state.render_mode,
        "updated": now.isoformat(timespec="seconds"),
        "pid": os.getpid(),
    })

@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    input_str = data.get("input", "")
    lines_count = data.get("lines_count", "auto")

    name = board_name()
    temp = cpu_temperature()
    up = uptime_text()

    with state.lock:
        lower = input_str.strip().lower()
        
        if lower in ("fill_max", "maksymalne", "wypelnij", "all_pixels"):
            state.mode = "DIAGNOSTICS"
            state.render_mode = None
            state.diagnostic_mode = "fill_max"
            state.current_rows = ["[Diagnostics: full 128x32 fill]"]
            add_to_history(state.current_rows, "DIAGNOSTICS")
            
            # Generate and display fill_max frame immediately
            image, _ = render_frame(state.device, [], diagnostic_mode="fill_max")
            try:
                if state.device: state.device.display(image)
            except Exception as i2c_err:
                print("I2C write error: %s" % i2c_err, file=sys.stderr)
            if state.args and state.args.frame_png:
                write_image_atomic(state.args.frame_png, image)
            
            return jsonify({
                "success": True,
                "mode": state.mode,
                "renderMode": None,
                "rows": state.current_rows,
                "history": state.history
            })
        
        if lower in ("demo", "demonstracja"):
            with state.lock:
                state.current_rows = ["[Demo]"]
                add_to_history(state.current_rows, "DIAGNOSTICS")
            
            # Run demo in background thread
            t = threading.Thread(target=run_demo, args=(state.device,), daemon=True)
            t.start()
            
            return jsonify({
                "success": True,
                "mode": "DIAGNOSTICS",
                "renderMode": None,
                "rows": ["[Demo]"],
                "history": state.history
            })
        
        # Standard text command
        new_mode, rows, render_mode = format_custom_text(input_str, lines_count, name, temp, up)
        state.mode = new_mode
        state.render_mode = render_mode
        state.diagnostic_mode = None
        if new_mode == "CUSTOM":
            state.current_rows = rows
            add_to_history(rows, "CUSTOM")
        else:
            state.current_rows = []

    return jsonify({
        "success": True,
        "mode": state.mode,
        "renderMode": state.render_mode,
        "rows": rows,
        "history": state.history
    })

@app.route("/api/history", methods=["GET"])
def api_history():
    with state.lock:
        return jsonify({"history": state.history})

@app.route("/api/history/restore/<entry_id>", methods=["POST"])
def api_restore(entry_id):
    with state.lock:
        target = None
        for entry in state.history:
            if entry["id"] == entry_id:
                target = entry
                break
        if not target:
            return jsonify({"success": False, "error": "Not found"}), 404

        state.mode = "CUSTOM"
        state.render_mode = None
        state.current_rows = target["rows"]
        # Also push to history as a new top restore entry or keep history as is
        add_to_history(target["rows"], "CUSTOM")

    return jsonify({
        "success": True,
        "mode": state.mode,
        "renderMode": state.render_mode,
        "rows": target["rows"],
        "history": state.history
    })

@app.route("/api/upload-image", methods=["POST"])
def api_upload_image():
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file provided"}), 400
    
    file = request.files["image"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400
    
    # Validate extension
    allowed_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    filename_lower = file.filename.lower()
    if not any(filename_lower.endswith(ext) for ext in allowed_extensions):
        return jsonify({"success": False, "error": "Invalid file type. Allowed: png, jpg, jpeg, bmp, webp"}), 400
    
    # Check file size (5MB limit)
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > 5 * 1024 * 1024:
        return jsonify({"success": False, "error": "File too large. Max 5MB"}), 400

    try:
        # Open and process image
        img = Image.open(file.stream)
        
        # Convert to grayscale
        img = img.convert("L")
        
        # Apply autocontrast
        img = ImageOps.autocontrast(img)
        
        # Resize with padding to 128x32
        img = ImageOps.pad(img, (128, 32), color=0)
        
        # Convert to 1-bit with dithering
        try:
            img = img.convert("1", dither=Image.FLOYDSTEINBERG)
        except (AttributeError, ValueError):
            try:
                img = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
            except Exception:
                img = img.convert("1")
        
        # Store in state
        with state.lock:
            state.mode = "IMAGE"
            state.render_mode = None
            state.custom_image = img
            state.custom_image_filename = file.filename
            state.scroll_offset = 0
            state.scroll_pause_until = 0
            
            # Add to history
            entry = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "rows": ["[Obraz: %s]" % file.filename],
                "mode": "IMAGE"
            }
            state.history.insert(0, entry)
            if len(state.history) > 20:
                state.history = state.history[:20]
        
        # Display immediately
        try:
            device = state.device
            if device:
                if state.device: state.device.display(img)
        except Exception as e:
            print("I2C display error after upload: %s" % e, file=sys.stderr)
        
        # Save frame
        if state.args and state.args.frame_png:
            write_image_atomic(state.args.frame_png, img)
        
        return jsonify({
            "success": True,
            "mode": "IMAGE",
            "renderMode": None,
            "rows": ["[Obraz: %s]" % file.filename],
            "history": state.history
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def detect_bus(address):
    try:
        from smbus2 import SMBus
    except ImportError:
        return None
    paths = sorted(glob.glob("/dev/i2c-*"),
                   key=lambda path: int(path.rsplit("-", 1)[1]))
    for path in paths:
        bus = int(path.rsplit("-", 1)[1])
        try:
            with SMBus(bus) as smbus:
                smbus.write_quick(address)
        except OSError:
            continue
        return bus
    return None

def release_device(device):
    """Close the I2C handle held by the previous luma device.

    Without this, every auto re-init leaves the old bus handle open and the
    service slowly runs out of file descriptors while systemd still reports it
    as active (status/PNG writes then fail silently).
    """
    if device is None or getattr(device, "is_dummy", False):
        return
    for target in (getattr(device, "_serial", None), device):
        cleanup = getattr(target, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception as err:
                print("device cleanup warning: %s" % err, file=sys.stderr)
            return

def build_device(args):
    """Create the OLED device object. The constructor sends the full init
    sequence (display on, charge pump, mux/mapping, contrast) to the panel."""
    if args.driver == "ssd1306":
        return ssd1306(i2c(port=args.bus, address=args.address),
                       width=args.width, height=args.height)
    return sh1106(i2c(port=args.bus, address=args.address),
                  width=args.width, height=args.height)

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SSD1306 status display and API server for Orange Pi Win")
    parser.add_argument("--bus", type=int, default=None,
                        help="I2C bus number (default: auto-detect)")
    parser.add_argument("--address", type=lambda value: int(value, 0),
                        default=DEFAULT_ADDRESS,
                        help="I2C address (default: 0x3c)")
    parser.add_argument("--width", type=int, default=128,
                        help="panel width in pixels (default: 128)")
    parser.add_argument("--height", type=int, default=32,
                        help="panel height: 32 (0.91\") or 64 (0.96\")")
    parser.add_argument("--driver", type=str, default="ssd1306",
                        choices=["ssd1306", "sh1106"],
                        help="OLED driver chip: ssd1306 (default) or sh1106")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="refresh interval in seconds (default: 1)")
    parser.add_argument("--port", type=int, default=5003,
                        help="Flask API port (default: 5003)")
    parser.add_argument("--threads", type=int, default=8,
                        help="WSGI worker threads when waitress is available (default: 8)")
    parser.add_argument("--status-json", default=STATUS_JSON,
                        help="live status for the web page")
    parser.add_argument("--frame-png", default=FRAME_PNG,
                        help="rendered frame for the web preview")
    args = parser.parse_args(argv)

    state.args = args
    bus = args.bus if args.bus is not None else detect_bus(args.address)
    if bus is None:
        print("Warning: no I2C bus answered on address 0x%02x - running in simulation/offline mode" % args.address, file=sys.stderr)
        bus = 1

    args.bus = bus
    name = board_name()

    try:
        device = build_device(args)
        state.device = device
        print("OLED: %s on bus %d, address 0x%02x, panel %dx%d, driver %s, refresh %.2fs"
              % (name, bus, args.address, args.width, args.height, args.driver, args.interval),
              flush=True)
    except Exception as e:
        print("Error initializing OLED device: %s (continuing with web API)" % e, file=sys.stderr)
        # Mock device object for headless/offline testing if needed
        class DummyDevice:
            width = args.width
            height = args.height
            is_dummy = True  # oled_loop periodycznie probuje zbudowac prawdziwe urzadzenie
            def display(self, img): pass
            def clear(self): pass
        state.device = DummyDevice()

    # Start OLED background thread
    t = threading.Thread(target=oled_loop, args=(state.device, args), daemon=True)
    t.start()

    print("Starting Flask API server on port %d" % args.port, flush=True)
    if waitress_serve is not None:
        print("Serving with waitress (%d worker threads)" % args.threads, flush=True)
        waitress_serve(app, host="0.0.0.0", port=args.port, threads=args.threads)
    else:
        print("waitress not installed - falling back to the Flask development server",
              flush=True)
        app.run(host="0.0.0.0", port=args.port, threaded=True, debug=False, use_reloader=False)

    return 0

if __name__ == "__main__":
    sys.exit(main())
