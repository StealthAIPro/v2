"""
Online statistics using Welford's algorithm.
Tracks mean and variance for streaming data without full history storage.
"""

import math
import threading


class WelfordStats:
    """
    Compute running mean and variance using Welford's online algorithm.
    Space: O(1), suitable for continuous data streams.
    """

    def __init__(self):
        self.n = 0
        self._mean = 0.0
        self._M2 = 0.0
        self._lock = threading.Lock()

    def update(self, x: float):
        """Add a new observation."""
        if not math.isfinite(x):
            raise ValueError("observation must be finite")
        with self._lock:
            self.n += 1
            delta = x - self._mean
            self._mean += delta / self.n
            delta2 = x - self._mean
            self._M2 += delta * delta2

    def reset(self):
        """Clear all data."""
        with self._lock:
            self.n = 0
            self._mean = 0.0
            self._M2 = 0.0

    def snapshot(self) -> dict[str, int | float]:
        """Return a consistent statistics snapshot."""
        with self._lock:
            variance = self._M2 / (self.n - 1) if self.n > 1 else 0.0
            return {
                "mean": self._mean,
                "std": math.sqrt(variance),
                "count": self.n,
            }

    @property
    def mean(self) -> float:
        """Current mean."""
        return float(self.snapshot()["mean"])

    @property
    def variance(self) -> float:
        """Current sample variance."""
        with self._lock:
            return self._M2 / (self.n - 1) if self.n > 1 else 0.0

    @property
    def std(self) -> float:
        """Current standard deviation."""
        return math.sqrt(self.variance)

    @property
    def count(self) -> int:
        """Number of samples seen."""
        return int(self.snapshot()["count"])
