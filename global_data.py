# ============================================================
#  Global shared state
# ============================================================
import threading

# Dict[patient_id -> {info, sensor}]
patients_data = {}

# First patient per ward gets real hardware data; others get simulated data.
REAL_PATIENT_IDS = {"icu": None, "incubator": None}

# ── Outgoing message queue (Main Center -> Ward via LoRa) ──
outgoing_messages = []
outgoing_lock = threading.Lock()

# ── Ward <-> Node ID mappings ──────────────────────────────
WARD_TO_NODE = {
    "icu": 1,
    "incubator": 2,
}

NODE_TO_WARD = {
    1: "icu",
    2: "incubator",
}
