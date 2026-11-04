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


class HookedClock(FakeClock):
    """FakeClock that fires callbacks when simulated time passes an offset (seconds from start)."""

    def __init__(self, start, jumps=None):
        super().__init__(start, jumps)
        self._start = start
        self._hooks = []

    def at(self, offset_seconds, callback):
        self._hooks.append((offset_seconds, callback))

    def elapsed(self):
        return (self._now - self._start).total_seconds()

    async def sleep(self, seconds):
        await super().sleep(seconds)
        for hook in [h for h in self._hooks if h[0] <= self.elapsed()]:
            self._hooks.remove(hook)
            hook[1]()


def probe(state="valid", *, marker=False, **override):
    """What the session probe script returns for a page in the given state."""
    base = {"host": "NCL", "path": "/NLT/co/multimedia.jsp", "logout": False, "records": False,
            "welcome": False, "agree_dialog": False, "date_grid": False,
            "login_marker": marker, "password_fields": 0}
    if state == "valid":
        base.update(logout=True, records=True, welcome=True)
    elif state == "login":
        base.update(password_fields=1)
    elif state == "offsite":
        return {"host": "OTHER"}
    base.update(override)
    return base


class Typing:
    def __init__(self, tab, kind):
        self.tab, self.kind = tab, kind

    async def clear_input(self):
        self.tab.log.append(("clear", self.kind))

    async def send_keys(self, text):
        self.tab.typed.append((self.kind, text))
        self.tab.log.append(("type", self.kind))

    async def click(self):
        self.tab.log.append(("click", self.kind))


class AuthTab:
    """A browser tab whose login state follows ``self.state`` (mutated by tests/hooks)."""

    def __init__(self, clock, state="valid", *, field_check=None, entry="GRID_READY"):
        self.clock, self.state, self.entry = clock, state, entry
        self.marker, self.log, self.typed, self.probe_error = False, [], [], False
        self.reload_error = None
        self.field_check = field_check or {"account": 1, "password": 1, "password_type": True,
                                           "account_type_ok": True, "same_form": True,
                                           "captcha_safe": True}
        self.overrides = {}
        self.terms = {"present": False, "hash": None}    # what the dialog probe reports
        self.dialog = False                              # whether the rules dialog is really shown
        self.agreed = False

    async def evaluate(self, script):
        if script == "location.href":
            return NCL_GRID_URL
        if "password_fields" in script and "logout" in script:
            if self.probe_error:
                raise OSError("tab crashed")
            self.log.append(("probe", self.state))
            return probe(self.state, marker=self.marker, **self.overrides)
        if script.startswith("(() => { window.__nclLoginMarker"):
            self.marker = True
            self.log.append(("marker",))
            return True
        if "same_form" in script:
            return self.field_check
        if "cyrb53" in script:
            return self.terms
        if "const action =" in script:
            self.log.append(("entry", "const action = true;" in script))
            if self.dialog and not self.agreed:
                if "const action = true;" in script:
                    self.agreed = True
                    return "GRID_READY"
                return "AGREEMENT_REQUIRED"
            return self.entry
        return None

    async def select(self, selector, timeout=10):
        return {"#acct": Typing(self, "account"), "#pass": Typing(self, "password"),
                "#captcha": Typing(self, "captcha")}.get(selector)

    async def reload(self, **kwargs):
        self.log.append(("reload", self.clock.now()))
        if self.reload_error:
            raise self.reload_error

    async def wait_for_ready_state(self, **kwargs):
        return None

    def count(self, kind):
        return sum(1 for entry in self.log if entry[0] == kind)
