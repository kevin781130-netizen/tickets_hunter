"""Deterministic fakes: a controllable clock and a recording browser tab."""
from datetime import timedelta

NCL_GRID_URL = "https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"


class FakeClock:
    """sleep() advances time instantly; ``jumps`` simulates a laptop sleeping."""

    def __init__(self, start, jumps=None):
        self._now = start
        self.sleeps = []
        self.jumps = dict(jumps or {})  # nth sleep (1-based) -> extra seconds that pass

    def now(self):
        return self._now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._now += timedelta(seconds=seconds)
        self._now += timedelta(seconds=self.jumps.pop(len(self.sleeps), 0))


class FakeTab:
    """Records when each page action happens on the fake clock."""

    def __init__(self, clock, *, reload_error=None, entry="GRID_READY"):
        self.clock, self.reload_error, self.entry = clock, reload_error, entry
        self.log = []

    async def reload(self, **kwargs):
        self.log.append(("reload", self.clock.now()))
        if self.reload_error:
            raise self.reload_error

    async def wait_for_ready_state(self, **kwargs):
        return None

    async def evaluate(self, script):
        if script == "location.href":
            return NCL_GRID_URL
        return self.entry

    def times(self, kind):
        return [stamp for name, stamp in self.log if name == kind]
