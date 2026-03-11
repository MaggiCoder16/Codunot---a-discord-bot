from datetime import datetime

class MemoryManager:
    def __init__(self, limit=60, file_path=None):
        self.limit = limit
        self.file_path = file_path

        # memory[channel_id] = {
        #     "messages": [...],
        #     "timestamps": [...],
        #     "roast_target": None,
        #     "mode": "funny",
        #     "model": "openai/gpt-oss-120b"
        # }
        self.memory = {}

        # flags[key] = True
        self.flags = {}

    # ---------------- MESSAGE LOGGING ----------------
    def add_message(self, channel_id, user, message):
        if channel_id not in self.memory:
            self.memory[channel_id] = {
                "messages": [],
                "timestamps": [],
                "roast_target": None,
                "mode": "funny",
                "model": "openai/gpt-oss-120b"
            }

        entry = f"{user}: {message}"

        self.memory[channel_id]["messages"].append(entry)
        self.memory[channel_id]["messages"] = self.memory[channel_id]["messages"][-self.limit:]

        self.memory[channel_id]["timestamps"].append(datetime.utcnow())
        self.memory[channel_id]["timestamps"] = self.memory[channel_id]["timestamps"][-self.limit:]

    def get_recent_flat(self, channel_id, n):
        if channel_id in self.memory:
            return self.memory[channel_id]["messages"][-n:]
        return []

    def get_last_timestamp(self, channel_id):
        if channel_id in self.memory and self.memory[channel_id]["timestamps"]:
            return self.memory[channel_id]["timestamps"][-1]
        return None

    # ---------------- ROAST TARGET ----------------
    def set_roast_target(self, channel_id, target_name):
        self._ensure_channel(channel_id)
        self.memory[channel_id]["roast_target"] = target_name

    def get_roast_target(self, channel_id):
        if channel_id in self.memory:
            return self.memory[channel_id]["roast_target"]
        return None

    def remove_roast_target(self, channel_id):
        if channel_id in self.memory:
            self.memory[channel_id]["roast_target"] = None

    # ---------------- CHANNEL MODE SAVE/LOAD ----------------
    def save_channel_mode(self, channel_id, mode):
        """
        Save the user's mode such as 'funny', 'serious', 'roast', 'chess'.
        """
        self._ensure_channel(channel_id)
        self.memory[channel_id]["mode"] = mode

    def get_channel_mode(self, channel_id):
        """
        Returns saved mode, or None if no mode exists.
        """
        if channel_id in self.memory:
            return self.memory[channel_id].get("mode")
        return None

    def save_channel_model(self, channel_id, model):
        self._ensure_channel(channel_id)
        self.memory[channel_id]["model"] = model

    def get_channel_model(self, channel_id):
        if channel_id in self.memory:
            return self.memory[channel_id].get("model", "openai/gpt-oss-120b")
        return "openai/gpt-oss-120b"

    def clear_channel_messages(self, channel_id):
        self._ensure_channel(channel_id)
        self.memory[channel_id]["messages"] = []
        self.memory[channel_id]["timestamps"] = []

    # ---------------- FLAGS ----------------
    def set_flag(self, key):
        self.flags[key] = True

    def get_flag(self, key):
        return self.flags.get(key, False)

    # ---------------- INTERNAL ----------------
    def _ensure_channel(self, channel_id):
        if channel_id not in self.memory:
            self.memory[channel_id] = {
                "messages": [],
                "timestamps": [],
                "roast_target": None,
                "mode": "funny",
                "model": "openai/gpt-oss-120b"
            }

    # ---------------- PERSIST (currently inactive) ----------------
    def persist(self):
        """
        You can implement JSON saving here if you want real persistence.
        Currently does nothing (same as your old version).
        """
        pass

    async def close(self):
        self.persist()
