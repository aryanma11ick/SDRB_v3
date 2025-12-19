import json
from datetime import datetime, timezone
import redis

REDIS_TTL_SECONDS = 15 * 24 * 60 * 60  # 15 days


class STMManager:
    def __init__(self):
        self.redis = redis.Redis(
            host="localhost",
            port=6379,
            decode_responses=True
        )

    def _key(self, thread_id: str) -> str:
        return f"stm:thread:{thread_id}"

    def get(self, thread_id: str) -> dict | None:
        data = self.redis.get(self._key(thread_id))
        return json.loads(data) if data else None

    def create_or_update(self, stm: dict):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()


        stm.setdefault("created_at", now)
        stm["last_updated"] = now

        self.redis.set(
            self._key(stm["thread_id"]),
            json.dumps(stm),
            ex=REDIS_TTL_SECONDS
        )

    def update_state(self, thread_id: str, new_state: str):
        stm = self.get(thread_id)
        if not stm:
            raise ValueError("STM not found")

        stm["state"] = new_state
        self.create_or_update(stm)

    def delete(self, thread_id: str):
        self.redis.delete(self._key(thread_id))

    def find_active_by_supplier_email(self, supplier_email_id: str) -> dict | None:
        if not supplier_email_id:
            return None

        normalized = supplier_email_id.lower()
        for key in self.redis.scan_iter(match="stm:thread:*"):
            ttl = self.redis.ttl(key)
            if ttl == -2:
                continue
            if ttl is not None and ttl <= 0:
                continue
            data = self.redis.get(key)
            if not data:
                continue
            record = json.loads(data)
            for candidate in record.get("supplier_email_ids", []):
                if isinstance(candidate, str) and candidate.lower() == normalized:
                    return record
        return None
