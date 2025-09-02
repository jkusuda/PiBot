import json
import os

DATA_FILE = "data.json"

# Ensure the file exists and is valid JSON
if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def assign_slot(user_id: str, time: str):
    data = load_data()
    data[user_id] = {
        "time": time,
        "booked": False
    }
    save_data(data)

def mark_booked(user_id: str):
    data = load_data()
    if user_id in data:
        data[user_id]["booked"] = True
        save_data(data)

def get_assignments():
    return load_data()
