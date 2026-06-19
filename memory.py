import os
import json
import config


class CampaignMemory:

    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.history = []
        self.world_state = {}
        self.players = {}
        self.data_dir = os.path.join(config.DATA_DIR, str(channel_id))
        os.makedirs(self.data_dir, exist_ok=True)
        self._load()

    def _file_path(self, name):
        return os.path.join(self.data_dir, f"{name}.json")

    def _load(self):
        path = self._file_path("campaign")
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                self.history = data.get("history", [])
                self.world_state = data.get("world_state", {})
                self.players = data.get("players", {})

    def _save(self):
        path = self._file_path("campaign")
        with open(path, "w") as f:
            json.dump({
                "history": self.history,
                "world_state": self.world_state,
                "players": self.players
            }, f, indent=2)

    def add_message(self, role, content):
        self.history.append({
            "role": role,
            "content": content
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()

    def get_history(self):
        return list(self.history)

    def get_context_string(self):
        parts = []
        if self.players:
            parts.append("Players: " + ", ".join(self.players.keys()))
        if self.world_state:
            parts.append("World state: " + json.dumps(self.world_state))
        if self.history:
            recent = self.history[-10:]
            for msg in recent:
                speaker = "Player" if msg["role"] == "user" else "DM"
                parts.append(f"{speaker}: {msg['content']}")
        return "\n".join(parts)

    def update_world_state(self, key, value):
        self.world_state[key] = value
        self._save()

    def add_player(self, name, info=""):
        self.players[name] = info
        self._save()

    def clear(self):
        self.history = []
        self.world_state = {}
        self.players = {}
        self._save()
