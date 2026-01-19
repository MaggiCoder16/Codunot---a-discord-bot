import json
import os
from datetime import date

TOTAL_COUNTS_FILE = "usage_counts.json"

def save_usage():
    data = {
        "date": date.today().isoformat(),  # for daily reset check
        "daily": {
            "messages": channel_usage,   # your current daily usage dict
            "images": channel_usage,     # if stored separately
            "files": channel_usage
        },
        "total": {
            "images": total_image_count,
            "files": total_file_count
        }
    }
    try:
        with open(TOTAL_COUNTS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[SAVE USAGE ERROR] {e}")

def load_usage():
    global channel_usage, total_image_count, total_file_count
    if os.path.exists(TOTAL_COUNTS_FILE):
        try:
            with open(TOTAL_COUNTS_FILE) as f:
                data = json.load(f)
                # Total counts
                total_image_count = {k:int(v) for k,v in data.get("total", {}).get("images", {}).items()}
                total_file_count = {k:int(v) for k,v in data.get("total", {}).get("files", {}).items()}
                
                # Daily counts
                saved_day = data.get("date")
                if saved_day == date.today().isoformat():
                    channel_usage.update(data.get("daily", {}))  # keep same daily counts
                else:
                    channel_usage.clear()  # reset daily if day changed
        except Exception as e:
            print(f"[LOAD USAGE ERROR] {e}")
            channel_usage = {}
            total_image_count = {}
            total_file_count = {}
    else:
        channel_usage = {}
        total_image_count = {}
        total_file_count = {}
