"""El reloj y el cronómetro del sistema."""

import time


class SystemClock:
    """El reloj del sistema, en segundos."""

    def now(self) -> int:
        return int(time.time())


class MonotonicTimer:
    """Un cronómetro que no retrocede aunque cambie la hora del sistema."""

    def now_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


system_clock = SystemClock()
