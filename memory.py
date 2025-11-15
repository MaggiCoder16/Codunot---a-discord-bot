from datetime import datetime

class MemoryManager:
    def __init__(self, limit=60, file_path=None):
        self.limit = limit
        self.file_path = file_path
        # Structure: {channel_id: {"messages":[], "timestamps":[], "user_moods":{}, "roast_target":None}}
        self.memory = {}

    # ---------- Message Memory ----------
    def add_message(self, channel_id, user, message):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "user_moods": {}, "roast_target": None}
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

    # ---------- Mood (optional) ----------
    def update_mood(self, channel_id, user, mood):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "user_moods": {}, "roast_target": None}
        self.memory[channel_id]["user_moods"][user] = mood

    def get_mood(self, channel_id, user):
        if channel_id in self.memory:
            return self.memory[channel_id]["user_moods"].get(user, None)
        return None

    # ---------- Roast Target ----------
    def set_roast_target(self, channel_id, target):
        if channel_id not in self.memory:
            self.memory[channel_id] = {"messages": [], "timestamps": [], "user_moods": {}, "roast_target": None}
        self.memory[channel_id]["roast_target"] = target

    def get_roast_target(self, channel_id):
        if channel_id in self.memory:
            return self.memory[channel_id].get("roast_target", None)
        return None

    # ---------- Persistence (optional) ----------
    def persist(self):
        # Optional: save memory to file
        pass

    async def close(self):
        self.persist()
