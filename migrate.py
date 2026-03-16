"""
Run this ONCE before deploying encryption to migrate your existing plain JSON files.
After running successfully, delete this script.

Usage:
    python migrate.py
"""

import json
import os
import sys

# Make sure ENCRYPTION_KEY is in env before importing encryption
from dotenv import load_dotenv
load_dotenv()

from encryption import save_encrypted

FILES = [
    "mod_data.json",
    "vote_unlocks.json",
    "codunot_memory.json",
    "playlists.json",
    "usage.json",
]

success = 0
skipped = 0
failed = 0

for filepath in FILES:
    if not os.path.exists(filepath):
        print(f"[SKIP] {filepath} — file not found, skipping")
        skipped += 1
        continue

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Validate it's actually plain JSON (not already encrypted)
        try:
            json.loads(content)
        except json.JSONDecodeError:
            print(f"[SKIP] {filepath} — doesn't look like plain JSON, may already be encrypted")
            skipped += 1
            continue

        # Back up the original just in case
        backup_path = filepath + ".bak"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[BACKUP] {filepath} → {backup_path}")

        # Write encrypted version
        save_encrypted(filepath, content)
        print(f"[OK] Migrated {filepath}")
        success += 1

    except Exception as e:
        print(f"[FAIL] {filepath} — {e}")
        failed += 1

print(f"\nDone. {success} migrated, {skipped} skipped, {failed} failed.")
if failed:
    print("Check the errors above before starting the bot.")
    sys.exit(1)
else:
    print("You can now start the bot with encryption active.")
    print("Once everything works, delete the .bak files and this script.")
