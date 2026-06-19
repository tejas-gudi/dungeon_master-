import os
import json
import config


class CampaignDatabase:

    def __init__(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        self.index_path = os.path.join(config.DATA_DIR, "index.json")
        self._load()

    def _load(self):
        if os.path.exists(self.index_path):
            with open(self.index_path, "r") as f:
                self.index = json.load(f)
        else:
            self.index = {}

    def _save(self):
        with open(self.index_path, "w") as f:
            json.dump(self.index, f, indent=2)

    def register_channel(self, channel_id, name=""):
        cid = str(channel_id)
        if cid not in self.index:
            self.index[cid] = {
                "name": name,
                "created": str(channel_id)
            }
            self._save()

    def get_channel(self, channel_id):
        return self.index.get(str(channel_id))

    def list_channels(self):
        return self.index
