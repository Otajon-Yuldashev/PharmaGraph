from datetime import datetime

cache = {}

def get(key):
    if key in cache:
        return cache[key]["value"]
    return None

def set(key, value):
    cache[key] = {
        "value":     value,
        "timestamp": datetime.now().isoformat()
    }

def get_all():
    return [
        {"query": k, "timestamp": v["timestamp"]}
        for k, v in cache.items()
    ]

    