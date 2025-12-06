import pytest
import time
import threading
from unittest.mock import patch
from src.main.security.ratelimiter import InMemoryRateLimiter

# --- START OF UNIT TESTS ---

@pytest.fixture
def basic_limiter():
    """Returns a limiter with a simple config: 2 requests per 10 seconds."""
    config = [{"limit": 2, "window": 10}]
    return InMemoryRateLimiter(config)

@pytest.fixture
def tiered_limiter():
    """Returns a tiered limiter: 2/sec (burst) AND 5/min (sustained)."""
    config = [
        {"limit": 2, "window": 1},  # Burst
        {"limit": 5, "window": 60}  # Sustained
    ]
    return InMemoryRateLimiter(config)

def test_allow_within_limit(basic_limiter):
    """Should allow requests up to the limit."""
    user = "user1"
    assert basic_limiter.is_allowed(user) is True
    assert basic_limiter.is_allowed(user) is True

def test_block_exceeding_limit(basic_limiter):
    """Should block the request that exceeds the limit."""
    user = "user1"
    basic_limiter.is_allowed(user) # 1st (Allowed)
    basic_limiter.is_allowed(user) # 2nd (Allowed)
    
    # 3rd request should fail (Limit is 2)
    assert basic_limiter.is_allowed(user) is False

def test_window_reset_with_mock_time(basic_limiter):
    """Should allow requests again after the time window passes."""
    user = "user1"
    
    # We patch 'time.time' so we don't have to actually wait 10 seconds
    with patch('time.time') as mock_time:
        # Start at time 1000
        mock_time.return_value = 1000
        basic_limiter.is_allowed(user) # 1 (Allowed)
        basic_limiter.is_allowed(user) # 2 (Allowed)
        assert basic_limiter.is_allowed(user) is False # 3 (Blocked)
        
        # Fast forward time by 11 seconds (window is 10s)
        mock_time.return_value = 1011
        
        # Should be allowed again
        assert basic_limiter.is_allowed(user) is True

def test_user_isolation(basic_limiter):
    """User A getting blocked should not affect User B."""
    # Block User A
    basic_limiter.is_allowed("userA")
    basic_limiter.is_allowed("userA")
    assert basic_limiter.is_allowed("userA") is False
    
    # User B should still be fresh
    assert basic_limiter.is_allowed("userB") is True

def test_tiered_limits_burst_logic(tiered_limiter):
    """Test that the burst limit triggers before the sustained limit."""
    user = "user1"
    
    # Rule 1: Max 2 per 1 second
    assert tiered_limiter.is_allowed(user) is True
    assert tiered_limiter.is_allowed(user) is True
    
    # This hits the BURST limit (3rd req in < 1 sec)
    assert tiered_limiter.is_allowed(user) is False 

def test_cleanup_logic():
    """Ensure old timestamps are removed from memory (prevent memory leaks)."""
    config = [{"limit": 10, "window": 5}]
    limiter = InMemoryRateLimiter(config)
    user = "test_user"

    with patch('time.time') as mock_time:
        # T=1000: Add a request
        mock_time.return_value = 1000
        limiter.is_allowed(user)
        
        # Internal check: list should have 1 item
        assert len(limiter.storage[user]) == 1
        
        # T=1006: Move past the window (5s)
        mock_time.return_value = 1006
        limiter.is_allowed(user) # This triggers cleanup before adding new
        
        # Internal check: The old timestamp (1000) should be gone.
        # The list should only contain the new timestamp (1006).
        assert len(limiter.storage[user]) == 1
        assert limiter.storage[user][0] == 1006

def test_thread_safety():
    """
    Spam the limiter with 50 threads at the same time.
    Without the Lock in the class, this would often crash or miscount.
    """
    config = [{"limit": 100, "window": 60}] # Large limit
    limiter = InMemoryRateLimiter(config)
    user = "concurrent_user"
    
    def hit_limiter():
        for _ in range(10):
            limiter.is_allowed(user)

    threads = []
    # Create 10 threads, each sending 10 requests = 100 total
    for _ in range(10):
        t = threading.Thread(target=hit_limiter)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # If thread safety works, we should have exactly 100 entries
    # (Or at least no exceptions were thrown during execution)
    assert len(limiter.storage[user]) == 100