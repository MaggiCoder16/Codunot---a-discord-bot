import json  
import os  
from datetime import datetime  
from typing import List, Optional, Dict, Any  
  
class MemoryManager:  
    def __init__(self, limit: int, file_path: str):  
        """Initialize memory manager with message limit and storage file."""  
        self.limit = limit  
        self.file_path = file_path  
        self.channels: Dict[str, List[Dict[str, Any]]] = {}  
        self._load()  
      
    def _load(self):  
        """Load memory from disk."""  
        if os.path.exists(self.file_path):  
            try:  
                with open(self.file_path, 'r') as f:  
                    self.channels = json.load(f)  
            except (json.JSONDecodeError, IOError):  
                self.channels = {}  
        else:  
            self.channels = {}  
      
    def add_message(self, channel_id: str, author_name: str, content: str):  
        """Add a message to the channel's memory."""  
        if channel_id not in self.channels:  
            self.channels[channel_id] = []  
          
        message = {  
            "author": author_name,  
            "content": content,  
            "timestamp": datetime.utcnow().isoformat()  
        }  
          
        self.channels[channel_id].append(message)  
          
        # Trim to limit  
        if len(self.channels[channel_id]) > self.limit:  
            self.channels[channel_id] = self.channels[channel_id][-self.limit:]  
      
    def get_recent_messages(self, channel_id: str, n: int) -> List[Dict[str, Any]]:  
        """Get the n most recent messages for a channel."""  
        if channel_id not in self.channels:  
            return []  
        return self.channels[channel_id][-n:]  
      
    def get_recent_flat(self, channel_id: str, n: int) -> List[str]:  
        """Get recent messages formatted as 'author: content' strings."""  
        messages = self.get_recent_messages(channel_id, n)  
        return [f"{msg['author']}: {msg['content']}" for msg in messages]  
      
    def get_last_timestamp(self, channel_id: str) -> Optional[datetime]:  
        """Get the timestamp of the last message in a channel."""  
        if channel_id not in self.channels or not self.channels[channel_id]:  
            return None  
          
        last_msg = self.channels[channel_id][-1]  
        try:  
            return datetime.fromisoformat(last_msg["timestamp"])  
        except (KeyError, ValueError):  
            return None  
      
    def persist(self):  
        """Save memory to disk."""  
        try:  
            with open(self.file_path, 'w') as f:  
                json.dump(self.channels, f, indent=2)  
        except IOError as e:  
            print(f"Error persisting memory: {e}")  
      
    async def close(self):  
        """Async cleanup method - persist before closing."""  
        self.persist()
