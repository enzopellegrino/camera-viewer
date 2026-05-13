import json
import uuid
from pathlib import Path


class ConfigManager:
    def __init__(self, config_path: "str | Path" = "config.json"):
        self.config_path = Path(config_path)
        self._config: dict = {}
        self.load()

    def load(self):
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        else:
            self._config = self._default_config()
            self.save()

        self._config.setdefault("cameras", [])
        self._config.setdefault("screens", [{"name": "Default", "layout": "auto", "cameras": []}])
        self._config.setdefault("settings", {})

        # Migrate old single-auth to multi-user list
        if "auth" in self._config and "users" not in self._config:
            from .auth_dialog import hash_password
            old = self._config.pop("auth")
            self._config["users"] = [{
                "id": uuid.uuid4().hex[:8],
                "username": old.get("username", "admin"),
                "password_hash": old.get("password_hash", hash_password("admin")),
                "role": "admin",
                "preferences": {},
            }]
            self.save()

        if "users" not in self._config:
            from .auth_dialog import hash_password
            self._config["users"] = [{
                "id": uuid.uuid4().hex[:8],
                "username": "admin",
                "password_hash": hash_password("admin"),
                "role": "admin",
                "preferences": {},
            }]

    def save(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    # ── Mutable references ─────────────────────────────────────────────────

    @property
    def cameras(self) -> list[dict]:
        return self._config["cameras"]

    @property
    def screens(self) -> list[dict]:
        return self._config["screens"]

    @property
    def settings(self) -> dict:
        return self._config.get("settings", {})

    @property
    def users(self) -> list[dict]:
        return self._config["users"]

    def camera_lookup(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.cameras}

    # ── User preferences ────────────────────────────────────────────────────

    def save_user_preferences(self, user_id: str, preferences: dict):
        for u in self.users:
            if u["id"] == user_id:
                u["preferences"] = preferences
                self.save()
                return

    # ── Default config ──────────────────────────────────────────────────────

    @staticmethod
    def _default_config() -> dict:
        from .auth_dialog import hash_password
        return {
            "cameras": [],
            "screens": [{"name": "Default", "layout": "auto", "cameras": []}],
            "settings": {
                "kiosk_mode": False,
                "reconnect_delay_ms": 5000,
                "default_screen": 0,
            },
            "users": [{
                "id": uuid.uuid4().hex[:8],
                "username": "admin",
                "password_hash": hash_password("admin"),
                "role": "admin",
                "preferences": {},
            }],
        }
