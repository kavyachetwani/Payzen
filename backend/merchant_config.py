"""Merchant policy configuration (Tier 2).

Loaded from Firestore "merchant_config/demo_store" or defaults.
The pipeline reads these at batch start and applies them to all decisions.
"""

import json
from pathlib import Path

DEFAULTS = {
    "sms_enabled": True,
    "calls_enabled": True,
    "call_min_amount": 2000,
    "sms_template": "Your {service} payment of ₹{amount} could not be processed. Tap to retry: {link}",
    "call_tone": "empathetic",
    "brand_name": "Demo Store",
    "auto_escalate": False,
    "max_discount_percent": 0,
}

CONFIG_PATH = Path(__file__).parent / "merchant_config.json"


class MerchantConfig:
    def __init__(self):
        self._config = dict(DEFAULTS)
        self._load()

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                saved = json.loads(CONFIG_PATH.read_text())
                self._config.update(saved)
            except (json.JSONDecodeError, IOError):
                pass

    def _save(self):
        CONFIG_PATH.write_text(json.dumps(self._config, indent=2))

    def get_all(self) -> dict:
        return dict(self._config)

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def update(self, updates: dict) -> dict:
        for k, v in updates.items():
            if k in DEFAULTS:
                self._config[k] = v
        self._save()
        return self.get_all()

    def apply_policy(self, action: str, amount: float) -> tuple[str, str | None]:
        """Apply merchant policy to an action. Returns (final_action, downgrade_reason)."""
        if action == "sms_then_retry" and not self._config["sms_enabled"]:
            return "auto_retry", "merchant policy: SMS disabled"

        if action == "call_then_retry":
            if not self._config["calls_enabled"]:
                if self._config["sms_enabled"]:
                    return "sms_then_retry", "merchant policy: calls disabled"
                return "auto_retry", "merchant policy: calls and SMS disabled"
            if amount < self._config["call_min_amount"]:
                if self._config["sms_enabled"]:
                    return "sms_then_retry", f"merchant policy: calls only above ₹{self._config['call_min_amount']}"
                return "auto_retry", f"merchant policy: calls only above ₹{self._config['call_min_amount']}, SMS disabled"

        return action, None
