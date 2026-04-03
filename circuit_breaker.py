import time
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    """Simple circuit breaker for external API calls.

    States:
    - CLOSED: normal operation, requests pass through
    - OPEN: too many failures, requests fail immediately
    - HALF_OPEN: after cooldown, allow one test request
    """

    def __init__(self, name: str, failure_threshold: int = 5, cooldown_seconds: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def can_proceed(self) -> bool:
        """Check if request should proceed."""
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - self.last_failure_time >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                logger.info(f"🔄 [{self.name}] Circuit HALF_OPEN — testing with one request")
                return True
            return False
        # HALF_OPEN: allow one test request
        return True

    def record_success(self):
        """Record a successful call."""
        if self.state == "HALF_OPEN":
            logger.info(f"✅ [{self.name}] Circuit CLOSED — API recovered")
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"🔴 [{self.name}] Circuit OPEN — {self.failure_count} failures, cooling down {self.cooldown_seconds}s")

# Module-level instances for each external service
gemini_breaker = CircuitBreaker("Gemini", failure_threshold=3, cooldown_seconds=120)
ebay_breaker = CircuitBreaker("eBay", failure_threshold=5, cooldown_seconds=60)
mercari_breaker = CircuitBreaker("Mercari", failure_threshold=5, cooldown_seconds=90)
