import json
import os
import time

class Cache:
    def __init__(self, config=None):
        self.cache_dir = ".cache"
        os.makedirs(self.cache_dir, exist_ok=True)

    def get(self, key: str, ttl_hours: float) -> str | None:
        path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(path):
            return None
        age_hours = (time.time() - os.path.getmtime(path)) / 3600
        if age_hours > ttl_hours:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def set(self, key: str, value: str):
        path = os.path.join(self.cache_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)

    def clear(self):
        import shutil
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
