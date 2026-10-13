import sqlite3

DB_PATH = "hospital.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL,
            age            INTEGER,
            admission_date TEXT,
            condition      TEXT,
            ward           TEXT    DEFAULT 'icu'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS icu_readings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id   INTEGER NOT NULL,
            patient_name TEXT    NOT NULL,
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
            pulse        INTEGER DEFAULT 0,
            spo2         INTEGER DEFAULT 0,
            temp_body    REAL    DEFAULT 0,
            ecg          INTEGER DEFAULT 0,
            ecg_lead_off INTEGER DEFAULT 0,
            air_quality  INTEGER DEFAULT 0,
            sound        INTEGER DEFAULT 0,
            temp_dht     REAL    DEFAULT 0,
            humidity     REAL    DEFAULT 0,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS incubator_readings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id   INTEGER NOT NULL,
            patient_name TEXT    NOT NULL,
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
            pulse        INTEGER DEFAULT 0,
            spo2         INTEGER DEFAULT 0,
            temp_body    REAL    DEFAULT 0,
            ecg          INTEGER DEFAULT 0,
            ecg_lead_off INTEGER DEFAULT 0,
            air_quality  INTEGER DEFAULT 0,
            sound        INTEGER DEFAULT 0,
            temp_dht     REAL    DEFAULT 0,
            humidity     REAL    DEFAULT 0,
            weight       REAL    DEFAULT 0,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sender     TEXT    NOT NULL,
            receiver   TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_read    INTEGER DEFAULT 0,
            delivered  INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def save_patient(name, age, admission_date, condition, ward="icu"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO patients (name, age, admission_date, condition, ward) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, age, admission_date, condition, ward)
    )
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid


def save_reading(pid, patient_name, ward, pulse, spo2, temp_body, ecg,
                 ecg_lead_off, air_quality, sound, temp_dht, humidity,
                 weight=0.0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if ward == "icu":
        table = "icu_readings"
        c.execute(f"""
            INSERT INTO {table}
                (patient_id, patient_name, pulse, spo2, temp_body, ecg,
                 ecg_lead_off, air_quality, sound, temp_dht, humidity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, patient_name, pulse, spo2, temp_body, ecg,
              int(ecg_lead_off), air_quality, sound, temp_dht, humidity))

        c.execute(f"""
            DELETE FROM {table}
            WHERE patient_id = ?
              AND id NOT IN (
                  SELECT id FROM {table}
                  WHERE patient_id = ?
                  ORDER BY id DESC LIMIT 2
              )
        """, (pid, pid))
    else:
        table = "incubator_readings"
        c.execute(f"""
            INSERT INTO {table}
                (patient_id, patient_name, pulse, spo2, temp_body, ecg,
                 ecg_lead_off, air_quality, sound, temp_dht, humidity, weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, patient_name, pulse, spo2, temp_body, ecg,
              int(ecg_lead_off), air_quality, sound, temp_dht, humidity, weight))

        c.execute(f"""
            DELETE FROM {table}
            WHERE patient_id = ?
              AND id NOT IN (
                  SELECT id FROM {table}
                  WHERE patient_id = ?
                  ORDER BY id DESC LIMIT 2
              )
        """, (pid, pid))

    conn.commit()
    conn.close()


def load_patients_from_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, age, admission_date, condition, ward FROM patients")
    rows = c.fetchall()
    conn.close()
    return rows


def delete_patient(pid, ward):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    table = "icu_readings" if ward == "icu" else "incubator_readings"
    c.execute("DELETE FROM patients WHERE id = ?", (pid,))
    c.execute(f"DELETE FROM {table} WHERE patient_id = ?", (pid,))
    conn.commit()
    conn.close()


def get_last_readings(pid, ward, limit=2):
    table = "icu_readings" if ward == "icu" else "incubator_readings"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(f"""
        SELECT * FROM {table} WHERE patient_id = ?
        ORDER BY id DESC LIMIT ?
    """, (pid, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Messaging ──────────────────────────────────────────────

def save_message(sender, receiver, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
        (sender, receiver, message)
    )
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_messages(ward, limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, sender, receiver, message, timestamp, is_read, delivered
        FROM messages
        WHERE sender = ? OR receiver = ?
        ORDER BY id DESC LIMIT ?
    """, (ward, ward, limit))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return list(reversed(rows))


def get_unread_count(receiver):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT COUNT(*) FROM messages WHERE receiver = ? AND is_read = 0",
        (receiver,)
    )
    count = c.fetchone()[0]
    conn.close()
    return count


def mark_messages_read(receiver):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE messages SET is_read = 1 WHERE receiver = ? AND is_read = 0",
        (receiver,)
    )
    conn.commit()
    conn.close()
