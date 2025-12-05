# export PYTHONPATH=$PYTHONPATH:$(pwd)/src/main && ./venv/bin/python src/test/test_local_limiter.py
import time

from ratelimiter import InMemoryRateLimiter

# Use the class provided above
limiter = InMemoryRateLimiter([
    {"limit": 2, "window": 5} # Allow 2 requests per 5 secs
])

user = "test_user"

print("--- Starting Burst Test ---")
print(f"Req 1: {limiter.is_allowed(user)}") # Should be True
print(f"Req 2: {limiter.is_allowed(user)}") # Should be True
print(f"Req 3: {limiter.is_allowed(user)}") # Should be False (Blocked)

print("\n--- Waiting 6 seconds ---")
time.sleep(6)

print(f"Req 4: {limiter.is_allowed(user)}") # Should be True (Window reset)