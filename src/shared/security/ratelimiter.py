import time
import threading
from typing import List, Dict

"""
Since this uses Local Memory (RAM):
-   Restarting the server resets the limits. 
-   If a user is blocked, and you restart the server, they are unblocked immediately.

Multiple Workers: If you run Uvicorn with multiple workers (uvicorn main:app --workers 4), each worker has its own memory. 
-   A user could theoretically hit 4x the limit (1x per worker).
"""
class InMemoryRateLimiter:
    def __init__(self, config: List[Dict[str, int]]):
        self.config = config
        self.storage = {} # format: {'user_id': [timestamp1, timestamp2...]}
        self.lock = threading.Lock() # Crucial for thread safety
        
        # We need to know the longest window to know when to clean up old data
        self.max_window = max(r['window'] for r in config)

    def is_allowed(self, user_id: str) -> bool:
        with self.lock: # Lock the storage while we read/write
            now = time.time()
            
            # 1. Initialize user if not exists
            if user_id not in self.storage:
                self.storage[user_id] = []
            
            history = self.storage[user_id]
            
            # 2. CLEANUP: Remove timestamps older than the largest window
            # We filter the list to keep only relevant timestamps
            # This prevents memory leaks (growing list forever)
            cutoff = now - self.max_window
            self.storage[user_id] = [ts for ts in history if ts > cutoff]
            
            # Update the reference to the cleaned list
            history = self.storage[user_id]

            # 3. CHECK RULES: Iterate through every rule in config
            for rule in self.config:
                limit = rule['limit']
                window = rule['window']
                
                # Count how many requests in THIS specific window
                # e.g., how many timestamps are > (now - 5 seconds)
                window_start = now - window
                request_count = sum(1 for ts in history if ts > window_start)
                
                if request_count >= limit:
                    print(f"⛔ BLOCKED: Hit limit of {limit} in {window}s")
                    return False
            
            # 4. If all checks pass, record this request
            history.append(now)
            return True
