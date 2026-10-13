import os
import threading
import time
from dotenv import load_dotenv
import global_data
from global_data import patients_data
from database import save_reading, save_message, save_patient

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[WARNING] requests not installed. Run: pip install requests")

SERIAL_PORT = "COM5"
BAUD_RATE   = 115200

# ╔══════════════════════════════════════════════════╗
# ║           Ubidots Settings                       ║
# ╚══════════════════════════════════════════════════╝
load_dotenv()
UBIDOTS_TOKEN = os.environ.get("UBIDOTS_TOKEN", "")
UBIDOTS_URL   = "https://industrial.api.ubidots.com/api/v1.6/devices/"
MAIN_DEVICE   = "medical-monitor"  # Main Centre dashboard - receives ALL data
DEVICE_LABELS = {
    1: "intensive_care_unit",    # ICU individual device
    2: "INCUBATOR",             # Incubator individual device
}
UBIDOTS_ENABLED = True
UBIDOTS_INTERVAL = 20  # Upload every 20 seconds per device (saves daily quota)

# Track last upload time per source
_last_upload = {1: 0, 2: 0}

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("pyserial not installed")

# frames لكل source
_hw_frames = {
    1: {"source":1,"pulse":0,"spo2":0,"temp_body":0.0,"ecg":0,
        "ecg_lead_off":False,"air_quality":0,"sound":0,
        "temp_dht":0.0,"humidity":0.0,"weight":0.0},
    2: {"source":2,"pulse":0,"spo2":0,"temp_body":0.0,"ecg":0,
        "ecg_lead_off":False,"air_quality":0,"sound":0,
        "temp_dht":0.0,"humidity":0.0,"weight":0.0},
}

_frame_lock = threading.Lock()

# ── Serial port reference (for writing messages) ──────────
_serial_port = None
_serial_lock = threading.Lock()

# ── Outgoing message queue ─────────────────────────────────
_outgoing = []
_out_lock = threading.Lock()


def send_serial_message(text):
    """Queue a message to be written to NodeMCU Serial.
    NodeMCU reads it → includes in SYN packet → LoRa → ESP32."""
    with _out_lock:
        _outgoing.append(text)
    print(f"[MSG QUEUED] {text}")


def _write_to_serial(text):
    global _serial_port
    with _serial_lock:
        if _serial_port and _serial_port.is_open:
            try:
                _serial_port.write((text + "\n").encode("utf-8"))
                _serial_port.flush()
                print(f"[SERIAL TX] {text}")
                return True
            except Exception as e:
                print(f"[SERIAL TX ERROR] {e}")
        else:
            print(f"[SERIAL TX FAILED] Port not open, cannot send: {text}")
    return False


def _process_outgoing():
    with _out_lock:
        msgs = list(_outgoing)
        _outgoing.clear()
    for msg in msgs:
        _write_to_serial(msg)


# ── Ubidots Upload ─────────────────────────────────────────

def _check_alarm(frame):
    """Check if sensor readings indicate an alarm condition."""
    pulse = frame.get("pulse", 0)
    spo2 = frame.get("spo2", 0)
    temp_body = frame.get("temp_body", 0)
    temp_dht = frame.get("temp_dht", 0)
    sound = frame.get("sound", 0)
    air_quality = frame.get("air_quality", 0)

    if temp_body > 38.0:
        return 1
    if temp_dht > 35.0:
        return 1
    if sound > 45:
        return 1
    if air_quality < 45:
        return 1
    if spo2 > 0 and spo2 < 70:
        return 1
    if pulse > 0 and (pulse < 40 or pulse > 120):
        return 1
    return 0


def _upload_to_ubidots(frame):
    """Upload sensor data to Ubidots - to individual device AND main centre."""
    if not UBIDOTS_ENABLED or not REQUESTS_AVAILABLE:
        return

    src = frame.get("source", 0)
    individual_device = DEVICE_LABELS.get(src)
    if not individual_device:
        return

    # Rate limit: only upload every UBIDOTS_INTERVAL seconds per device
    now = time.time()
    if now - _last_upload.get(src, 0) < UBIDOTS_INTERVAL:
        return
    _last_upload[src] = now

    alarm = _check_alarm(frame)

    payload = {
        "pulse":       frame.get("pulse", 0),
        "spo2":        frame.get("spo2", 0),
        "temp-body":   frame.get("temp_body", 0),
        "ecg":         frame.get("ecg", 0),
        "humidity":    frame.get("humidity", 0),
        "temp-dht":    frame.get("temp_dht", 0),
        "air-quality": frame.get("air_quality", 0),
        "sound":       frame.get("sound", 0),
        "source":      src,
        "alarm":       alarm,
    }

    headers = {
        "X-Auth-Token": UBIDOTS_TOKEN,
        "Content-Type": "application/json",
    }

    # Upload to individual device (ICU or Incubator)
    try:
        url = UBIDOTS_URL + individual_device
        r = requests.post(url, headers=headers, json=payload, timeout=5)
        if r.status_code in (200, 201):
            print(f"[UBIDOTS] ✅ → {individual_device}")
        else:
            print(f"[UBIDOTS] ❌ {individual_device}: HTTP {r.status_code}")
    except Exception as e:
        print(f"[UBIDOTS] ❌ {individual_device}: {e}")

    # Upload to Main Centre device (for combined dashboard)
    try:
        url = UBIDOTS_URL + MAIN_DEVICE
        r = requests.post(url, headers=headers, json=payload, timeout=5)
        if r.status_code in (200, 201):
            print(f"[UBIDOTS] ✅ → {MAIN_DEVICE} (src={src})")
        else:
            print(f"[UBIDOTS] ❌ {MAIN_DEVICE}: HTTP {r.status_code}")
    except Exception as e:
        print(f"[UBIDOTS] ❌ {MAIN_DEVICE}: {e}")


def _parse_raw(line: str):
    try:
        if "RAW:" not in line:
            return None

        raw = line.split("RAW:")[-1].strip()

        if not raw.endswith("END"):
            return None

        parts = raw.split("|")

        frame = {}
        src = 0
        msg_text = ""

        for seg in parts:
            if seg.startswith("ID:"):
                src = int(seg[3:])
                frame["source"] = src
            elif seg.startswith("P:"):
                frame["pulse"] = int(seg[2:])
            elif seg.startswith("O:"):
                frame["spo2"] = int(seg[2:])
            elif seg.startswith("T:"):
                frame["temp_body"] = float(seg[2:])
            elif seg.startswith("E:"):
                frame["ecg"] = int(seg[2:])
            elif seg.startswith("L:"):
                frame["ecg_lead_off"] = (seg[2:] == "1")
            elif seg.startswith("A:"):
                frame["air_quality"] = int(seg[2:])
            elif seg.startswith("M:"):
                frame["sound"] = int(seg[2:])
            elif seg.startswith("D:"):
                dht = seg[2:].split("/")
                if len(dht) == 2:
                    frame["temp_dht"] = float(dht[0])
                    frame["humidity"]  = float(dht[1])
            elif seg.startswith("W:"):
                frame["weight"] = float(seg[2:])
            elif seg.startswith("MSG:"):
                msg_text = seg[4:]

        # ── Save incoming message from ward ──
        if msg_text and src in (1, 2):
            ward = "icu" if src == 1 else "incubator"

            # ── Auto-add patient from ward ──
            if msg_text.startswith("NEWPATIENT;"):
                parts = msg_text.split(";")
                if len(parts) >= 5:
                    p_name = parts[1]
                    p_age = parts[2]
                    p_date = parts[3]
                    p_cond = parts[4]
                    pid = save_patient(p_name, p_age, p_date, p_cond, ward)
                    patients_data[pid] = {
                        "info": {
                            "name": p_name, "age": p_age,
                            "admission_date": p_date,
                            "condition": p_cond, "ward": ward
                        },
                        "sensor": {
                            "pulse":0,"spo2":0,"temp_body":0.0,"ecg":0,
                            "ecg_lead_off":False,"air_quality":0,"sound":0,
                            "temp_dht":0.0,"humidity":0.0,"weight":0.0
                        }
                    }
                    if global_data.REAL_PATIENT_IDS.get(ward) is None:
                        global_data.REAL_PATIENT_IDS[ward] = pid
                    print(f"[AUTO-ADD] Patient '{p_name}' added to {ward} (pid={pid})")
            else:
                print(f"[MSG FROM {ward.upper()}] {msg_text}")
                save_message(ward, "main", msg_text)

        if src in (1, 2) and "spo2" in frame:
            if "weight" not in frame:
                frame["weight"] = 0.0
            print(f"[PARSED] src={src} pulse={frame.get('pulse')} spo2={frame.get('spo2')}")
            return frame

    except Exception as e:
        print("[PARSE ERROR]", e)

    return None


def _serial_reader():
    global _serial_port
    while True:
        ser = None
        try:
            ser = serial.Serial()
            ser.port = SERIAL_PORT
            ser.baudrate = BAUD_RATE
            ser.timeout = 3
            ser.dtr = False
            ser.rts = False
            ser.open()

            time.sleep(2)
            print(f"Serial connected on {SERIAL_PORT}")

            with _serial_lock:
                _serial_port = ser

            while True:
                # ── Send any pending outgoing messages ──
                _process_outgoing()

                line = ser.readline().decode("utf-8", errors="ignore").strip()

                if not line:
                    continue

                if "RAW:" not in line:
                    continue

                frame = _parse_raw(line)

                if frame:
                    src = frame["source"]
                    with _frame_lock:
                        _hw_frames[src].update(frame)

                    # Upload to Ubidots in background thread
                    threading.Thread(target=_upload_to_ubidots, args=(dict(frame),), daemon=True).start()

        except Exception as e:
            print("Serial error:", e)
            with _serial_lock:
                _serial_port = None
            if ser:
                try: ser.close()
                except: pass
            time.sleep(3)


def _update_loop():
    while True:
        try:
            if not patients_data:
                time.sleep(1)
                continue

            with _frame_lock:
                frames = {s: dict(f) for s, f in _hw_frames.items()}

            for pid in list(patients_data.keys()):

                patient = patients_data[pid]
                ward = patient["info"].get("ward", "icu")

                # All patients get real sensor data from their ward's ESP32
                src = 1 if ward == "icu" else 2
                frame = frames[src]
                sensor = {k: v for k, v in frame.items() if k != "source"}
                patient["sensor"].update(sensor)

                if sensor.get("spo2", 0) > 0:
                    print(f"[UPDATE] pid={pid} ward={ward} pulse={sensor['pulse']} spo2={sensor['spo2']}")
                else:
                    print(f"[UPDATE] pid={pid} ward={ward} pulse={sensor['pulse']} spo2=SENSOR_ERROR")

                save_reading(
                        pid,
                        patient["info"]["name"],
                        ward,
                        sensor["pulse"],
                        sensor["spo2"],
                        sensor["temp_body"],
                        sensor["ecg"],
                        sensor["ecg_lead_off"],
                        sensor["air_quality"],
                        sensor["sound"],
                        sensor["temp_dht"],
                        sensor["humidity"],
                        sensor["weight"],
                    )

            time.sleep(2)

        except Exception as e:
            print("Update error:", e)
            time.sleep(2)


def start_serial_thread():
    t1 = threading.Thread(target=_update_loop, daemon=True)
    t1.start()

    if SERIAL_AVAILABLE:
        t2 = threading.Thread(target=_serial_reader, daemon=True)
        t2.start()
