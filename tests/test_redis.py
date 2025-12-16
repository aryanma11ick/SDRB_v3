import redis

r = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)

r.set("test:key", "hello redis", ex=10)
print("Value:", r.get("test:key"))
