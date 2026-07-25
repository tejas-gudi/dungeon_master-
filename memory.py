import os
import json
import glob
from datetime import datetime, timezone

import config


class CampaignMemory:

    def __init__(self, channel_id):
        self.channel_id = channel_id
        self.data_dir = os.path.join(config.DATA_DIR, str(channel_id))
        self.sessions_dir = os.path.join(self.data_dir, "sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)

        self.state_path = os.path.join(self.data_dir, "state.json")
        self.summary_path = os.path.join(self.data_dir, "summary.md")
        self.legacy_path = os.path.join(self.data_dir, "campaign.json")

        self.state = self._default_state()
        self._load()

    def _default_state(self):
        return {
            "world_state": {},
            "players": {},
            "turn_order": [],
            "turn_index": 0,
            "turns_enabled": False,
            "messages_since_summary": 0
        }

    def _load(self):
        if os.path.exists(self.state_path):
            with open(self.state_path, "r") as f:
                loaded = json.load(f)
            self.state.update(loaded)
            return

        if os.path.exists(self.legacy_path):
            self._migrate_legacy()

        self._save_state()

    def _migrate_legacy(self):
        with open(self.legacy_path, "r") as f:
            legacy = json.load(f)

        history = legacy.get("history", [])
        legacy_session_path = os.path.join(self.sessions_dir, "legacy_import.jsonl")
        with open(legacy_session_path, "w") as f:
            for entry in history:
                line = {
                    "ts": None,
                    "role": entry.get("role", "user"),
                    "user_id": None,
                    "speaker": None,
                    "content": entry.get("content", "")
                }
                f.write(json.dumps(line) + "\n")

        self.state["world_state"] = legacy.get("world_state", {})
        print(f"[MEMORY] Migrated {len(history)} legacy messages for channel {self.channel_id}")

    def _save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    # --- character / player identity ---

    def set_character(self, user_id, discord_name, character_name):
        self.state["players"][str(user_id)] = {
            "discord_name": discord_name,
            "character_name": character_name
        }
        self._save_state()

    def get_character(self, user_id, fallback=None):
        entry = self.state["players"].get(str(user_id))
        if entry:
            return entry["character_name"]
        return fallback

    # --- turns ---

    def enable_turns(self):
        self.state["turns_enabled"] = True
        if not self.state["turn_order"]:
            self.state["turn_order"] = list(self.state["players"].keys())
        self._save_state()

    def disable_turns(self):
        self.state["turns_enabled"] = False
        self._save_state()

    def register_for_turns(self, user_id):
        uid = str(user_id)
        if self.state["turns_enabled"] and uid not in self.state["turn_order"]:
            self.state["turn_order"].append(uid)
            self._save_state()

    def current_turn_user_id(self):
        order = self.state["turn_order"]
        if not order:
            return None
        idx = self.state["turn_index"] % len(order)
        return order[idx]

    def advance_turn(self):
        order = self.state["turn_order"]
        if not order:
            return
        self.state["turn_index"] = (self.state["turn_index"] + 1) % len(order)
        self._save_state()

    def skip_turn(self):
        self.advance_turn()

    def is_players_turn(self, user_id):
        if not self.state["turns_enabled"]:
            return True
        current = self.current_turn_user_id()
        if current is None:
            return True
        return str(user_id) == current

    def turn_order_display(self, resolve_name):
        order = self.state["turn_order"]
        current = self.current_turn_user_id()
        parts = []
        for uid in order:
            name = resolve_name(uid)
            parts.append(f"-> {name}" if uid == current else f"   {name}")
        return "\n".join(parts) if parts else "(no players in turn order yet)"

    # --- messages ---

    def _today_session_path(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.sessions_dir, f"{date_str}.jsonl")

    def append_message(self, role, user_id, speaker, content):
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "user_id": str(user_id) if user_id is not None else None,
            "speaker": speaker,
            "content": content
        }
        with open(self._today_session_path(), "a") as f:
            f.write(json.dumps(line) + "\n")

        self.state["messages_since_summary"] += 1
        self._save_state()

    def _session_files(self):
        return sorted(glob.glob(os.path.join(self.sessions_dir, "*.jsonl")))

    def _tail_entries(self, n):
        files = self._session_files()
        lines = []
        for path in reversed(files):
            with open(path, "r") as f:
                file_lines = [json.loads(l) for l in f if l.strip()]
            lines = file_lines + lines
            if len(lines) >= n:
                break
        return lines[-n:]

    def get_recent_context(self, n=20):
        recent = self._tail_entries(n)
        history = []
        for entry in recent:
            speaker = entry.get("speaker")
            content = entry["content"]
            text = f"{speaker}: {content}" if speaker else content
            history.append({"role": entry["role"], "content": text})
        return history

    # --- summary ---

    def get_summary(self):
        if os.path.exists(self.summary_path):
            with open(self.summary_path, "r") as f:
                return f.read().strip()
        return ""

    def set_summary(self, text):
        with open(self.summary_path, "w") as f:
            f.write(text)

    def messages_since_summary(self):
        return self.state["messages_since_summary"]

    def reset_summary_counter(self):
        self.state["messages_since_summary"] = 0
        self._save_state()

    def get_messages_for_summary(self, n=None):
        n = n or config.SUMMARY_TRIGGER_MESSAGE_COUNT
        recent = self._tail_entries(n)
        return [
            {"speaker": e.get("speaker") or e["role"], "content": e["content"]}
            for e in recent
        ]

    # --- recall ---

    def search_sessions(self, keyword, limit=5):
        keyword_lower = keyword.lower()
        matches = []
        for path in reversed(self._session_files()):
            with open(path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if keyword_lower in entry["content"].lower():
                        matches.append(entry)
            if len(matches) >= limit:
                break
        return matches[:limit]

    # --- world state ---

    def update_world_state(self, key, value):
        self.state["world_state"][key] = value
        self._save_state()

    def clear(self):
        self.state = self._default_state()
        self._save_state()
        if os.path.exists(self.summary_path):
            os.remove(self.summary_path)
        for path in self._session_files():
            os.remove(path)
