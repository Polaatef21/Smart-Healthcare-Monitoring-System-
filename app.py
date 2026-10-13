from flask import Flask, jsonify, render_template, request, redirect
import global_data
from global_data import patients_data
from serial_thread import start_serial_thread, send_serial_message
from database import (init_db, save_patient, delete_patient,
                      load_patients_from_db, save_message,
                      get_messages, get_unread_count, mark_messages_read)

app = Flask(__name__)

# ── Startup ────────────────────────────────────────────────
init_db()

def _default_sensor():
    return {
        "pulse": 0, "spo2": 0, "temp_body": 0.0,
        "ecg": 0, "ecg_lead_off": False,
        "air_quality": 0, "sound": 0,
        "temp_dht": 0.0, "humidity": 0.0,
        "weight": 0.0
    }

# Restore patients from DB on startup
for row in load_patients_from_db():
    pid, name, age, admission_date, condition, ward = row
    patients_data[pid] = {
        "info": {
            "name": name, "age": age,
            "admission_date": admission_date,
            "condition": condition, "ward": ward
        },
        "sensor": _default_sensor()
    }

for pid, pdata in patients_data.items():
    w = pdata["info"]["ward"]
    if global_data.REAL_PATIENT_IDS.get(w) is None:
        global_data.REAL_PATIENT_IDS[w] = pid
    else:
        global_data.REAL_PATIENT_IDS[w] = min(global_data.REAL_PATIENT_IDS[w], pid)

start_serial_thread()


# ── Pages ──────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("home_dashboard.html")

@app.route("/form")
def form():
    return render_template("patient_form.html")

@app.route("/dashboard/<int:pid>")
def dashboard(pid):
    patient = patients_data.get(pid)
    if not patient:
        return "Patient not found", 404
    return render_template("index.html", patient=patient["info"], pid=pid)

@app.route("/ward/<ward>")
def ward_page(ward):
    if ward not in ("icu", "incubator"):
        return "Invalid ward", 404
    return render_template("ward_dashboard.html", ward=ward)


# ── Patient CRUD ───────────────────────────────────────────
@app.route("/patient", methods=["POST"])
def add_patient():
    name           = request.form["name"]
    age            = request.form["age"]
    admission_date = request.form["admission_date"]
    condition      = request.form["condition"]
    ward           = request.form.get("ward", "icu")

    pid = save_patient(name, age, admission_date, condition, ward)

    if global_data.REAL_PATIENT_IDS.get(ward) is None:
        global_data.REAL_PATIENT_IDS[ward] = pid

    patients_data[pid] = {
        "info": {
            "name": name, "age": age,
            "admission_date": admission_date,
            "condition": condition, "ward": ward
        },
        "sensor": _default_sensor()
    }
    return redirect("/")

@app.route("/delete_patient/<int:pid>", methods=["DELETE"])
def remove_patient(pid):
    patient = patients_data.get(pid)
    ward = patient["info"].get("ward", "icu") if patient else "icu"
    delete_patient(pid, ward)
    patients_data.pop(pid, None)
    return jsonify({"status": "deleted"})


# ── Data APIs ──────────────────────────────────────────────
@app.route("/all_data")
def all_data():
    return jsonify(patients_data)

@app.route("/ward_data/<ward>")
def ward_data(ward):
    filtered = {
        pid: pdata
        for pid, pdata in patients_data.items()
        if pdata["info"].get("ward") == ward
    }
    return jsonify(filtered)

@app.route("/data/<int:pid>")
def get_patient_data(pid):
    p = patients_data.get(pid)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p["sensor"])


# ── Messaging APIs ─────────────────────────────────────────

@app.route("/send_message", methods=["POST"])
def send_message():
    body = request.get_json(force=True)
    sender   = body.get("sender", "").strip()
    receiver = body.get("receiver", "").strip()
    message  = body.get("message", "").strip()

    if not sender or not receiver or not message:
        return jsonify({"error": "Missing fields"}), 400

    # Save to database
    msg_id = save_message(sender, receiver, message)

    # If Main Center sending to a ward → write to Serial → NodeMCU → LoRa → ESP32
    if sender == "main" and receiver in ("icu", "incubator"):
        send_serial_message(message)

    return jsonify({"status": "sent", "id": msg_id})


@app.route("/get_messages/<ward>")
def get_ward_messages(ward):
    msgs = get_messages(ward)
    return jsonify(msgs)


@app.route("/unread_count/<receiver>")
def unread_count(receiver):
    count = get_unread_count(receiver)
    return jsonify({"count": count})


@app.route("/mark_read/<receiver>", methods=["POST"])
def mark_read(receiver):
    mark_messages_read(receiver)
    return jsonify({"status": "ok"})


# ── Run ────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", use_reloader=False)
