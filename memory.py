from datetime import datetime

class MemoryManager:
    def __init__(self, limit=60, file_path=None):
        self.limit = limit
        self.file_path = file_path
        self.memory = {}  # {channel_id: {"messages":[], "timestamps":[], "roast_target":None}}
        self.flags = {}   # new dictionary to store simple boolean flags

    def add_message(self, channel_id, user, message):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "roast_target": None}
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

    # ----- Roast persistence -----
    def set_roast_target(self, channel_id, target_name):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "roast_target": None}
        self.memory[channel_id]["roast_target"] = target_name

    def get_roast_target(self, channel_id):
        if channel_id in self.memory:
            return self.memory[channel_id]["roast_target"]
        return None

    def remove_roast_target(self, channel_id):
        if channel_id in self.memory:
            self.memory[channel_id]["roast_target"] = None

    # ----- Flags for things like DM intro -----
    def get_flag(self, key):
        return self.flags.get(key, False)

    def set_flag(self, key, value=True):
        self.flags[key] = value

    # ----- Dummy persist for now -----
    def persist(self):
        pass

    async def close(self):
        self.persist()
