from datetime import datetime

class MemoryManager:
    def __init__(self, limit=60, file_path=None):
        self.limit = limit
        self.file_path = file_path
        self.memory = {}  # {channel_id: {"messages":[], "timestamps":[], "user_moods":{}}}
        self.roast_targets = {}  # {channel_id: target_name}

    def add_message(self, channel_id, user, message):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "user_moods": {}}
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

    # ---------- Roast target ----------
    def set_roast_target(self, channel_id, target_name):
        self.roast_targets[channel_id] = target_name

    def get_roast_target(self, channel_id):
        return self.roast_targets.get(channel_id, None)

    def clear_roast_target(self, channel_id):
        if channel_id in self.roast_targets:
            del self.roast_targets[channel_id]

    def persist(self):
        pass

    async def close(self):
        self.persist()
