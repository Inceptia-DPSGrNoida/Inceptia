"""
Meme-Off — Buzzer server (v3: team codes + hardened)

Run locally:   uvicorn cipher_server:app --port 8000 --ws-max-size 4096
Deploy:        uvicorn cipher_server:app --host 0.0.0.0 --port $PORT --ws-max-size 4096

Routes:
  /         -> index.html  (team screen: locked until a valid team code is entered)
  /host     -> host.html   (host panel: password, then manage team codes)
  /ws       -> WebSocket used by both pages
  /healthz  -> health check

Environment variables (all optional):
  HOST_PASSWORD   host panel password (set this in production)
  STATE_FILE      where teams, codes and scores are saved   (default: cipher_state.json)
  TRUST_PROXY=1   take the client IP from X-Forwarded-For (only behind a real proxy)

Needs:  pip install fastapi "uvicorn[standard]"

How team codes work
  * The host allots teams in the panel (name + code). Codes are generated, or typed in.
  * A device is only let in by entering a code that exists. Anyone else stays locked out:
    the server sends them no game data and ignores every buzz from them.
  * Codes are only ever sent to the host. Teams, and the public scoreboard, only see names.
  * Wrong guesses are throttled per device and per network.

Safety locks
  1. STATE_LOCK     every state change runs one at a time (buzz order = arrival order).
  2. Epoch guard    the auto-lock after a buzz can never re-lock a question that was reopened.
  3. Entry gate     no valid code = no state, no buzzing, no scoreboard.
  4. Host auth      host commands need the password (constant-time check, lock-out on repeats).
  5. Team binding   a device can only buzz as the team its code belongs to.
  6. Debounce       accidental double-clicks (score, next round, unlock...) are ignored.
  7. Flood limits   message size, per-socket rate, and team count are capped.
  8. Persistence    teams, codes, scores and round are saved atomically across restarts.
"""

import asyncio
import hmac
import json
import os
import re
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

BASE_DIR = Path(__file__).parent

# ── settings ───────────────────────────────────────────────────────────
# After the first buzz the buzzer stays open this many seconds so near-simultaneous
# presses still get ranked (#2, #3...), then it locks. Set to 0 for strict first-only.
BUZZ_GRACE = 0.3

HOST_PASSWORD = os.getenv("HOST_PASSWORD", "RasnaKaGuavaJuice")
STATE_FILE = Path(os.getenv("STATE_FILE", str(BASE_DIR / "cipher_state.json")))
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"

MAX_TEAMS = 100
MAX_NAME_LEN = 30
MIN_CODE_LEN, MAX_CODE_LEN, GEN_CODE_LEN = 4, 12, 6
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L: easy to read aloud
MAX_ADD_BATCH = 60
MAX_MSG_CHARS = 8192              # fits a pasted list of ~60 team names
MAX_SCORE_STEP = 100              # largest single score change the host can send
SEND_TIMEOUT = 1.0                # a client that can't take a message in 1s is dropped
RATE_CAPACITY, RATE_REFILL = 30, 15.0   # per-socket token bucket (burst, per second)
LOGIN_MAX_FAILS, LOGIN_LOCK_SECS = 5, 60          # host password
CODE_MAX_FAILS, CODE_COOLDOWN_SECS = 5, 15        # wrong team codes per device
IP_MAX_CODE_FAILS, IP_WINDOW_SECS = 40, 60        # wrong team codes per network (shared Wi-Fi friendly)

# Minimum seconds between identical host commands (ignores accidental double-clicks)
DEBOUNCE = {"score": 0.4, "next_round": 2.0, "unlock": 0.5, "reset": 0.3, "remove_team": 1.0,
            "add_teams": 0.5, "set_code": 0.5, "regen_code": 1.0}

app = FastAPI()

state = {
    "locked": True,
    "round": 1,
    "buzz_order": [],          # team names in the order they buzzed
    "teams": {},               # NAME -> {"score": int, "code": str}   (code is host-only)
    "epoch": 0,                # bumps whenever a question is opened / closed / reset
}
STATE_LOCK = asyncio.Lock()
conns: set = set()
_bg_tasks: set = set()
_last_cmd: dict = {}
_login_fails: dict = {}        # ip -> [fail_count, locked_until]   (host password)
_ip_code_fails: dict = {}      # ip -> deque of timestamps          (team codes)


# ── connection wrapper ─────────────────────────────────────────────────
class Conn:
    __slots__ = ("ws", "team", "is_host", "tokens", "stamp", "code_fails", "cooldown_until")

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.team: Optional[str] = None
        self.is_host = False
        self.tokens = float(RATE_CAPACITY)
        self.stamp = time.monotonic()
        self.code_fails = 0
        self.cooldown_until = 0.0

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(RATE_CAPACITY, self.tokens + (now - self.stamp) * RATE_REFILL)
        self.stamp = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


# ── helpers ────────────────────────────────────────────────────────────
def clean_name(raw) -> str:
    # Pages inject team names into innerHTML, so only allow safe characters.
    name = re.sub(r"[^A-Za-z0-9 _\-.]", "", str(raw or ""))
    return re.sub(r"\s+", " ", name).strip().upper()[:MAX_NAME_LEN]


def clean_code(raw) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())[:MAX_CODE_LEN]


def valid_code(code: str) -> bool:
    return MIN_CODE_LEN <= len(code) <= MAX_CODE_LEN


def code_in_use(code: str, ignore_team: str = "") -> bool:
    return any(t["code"] == code for n, t in state["teams"].items() if n != ignore_team)


def new_code() -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(GEN_CODE_LEN))
        if not code_in_use(code):
            return code


def find_team_by_code(code: str) -> Optional[str]:
    """Constant-time style lookup: always compares against every code."""
    found = None
    probe = code.encode("utf-8")
    for name, t in state["teams"].items():
        if hmac.compare_digest(probe, t["code"].encode("utf-8")):
            found = name
    return found


def online_teams() -> set:
    return {c.team for c in conns if c.team}


def public_state() -> dict:
    """What every admitted team sees. Never contains codes."""
    order = state["buzz_order"]
    online = online_teams()
    return {
        "locked": state["locked"],
        "round": state["round"],
        "buzz_order": list(order),
        "teams": {
            n: {"score": t["score"],
                "rank": (order.index(n) + 1) if n in order else None,
                "online": n in online}
            for n, t in state["teams"].items()
        },
    }


def state_payload() -> str:
    return json.dumps({"type": "state", "state": public_state()})


def host_teams_payload() -> str:
    """Host only: the secret codes."""
    online = online_teams()
    return json.dumps({"type": "host_teams", "teams": [
        {"name": n, "code": t["code"], "online": n in online}
        for n, t in sorted(state["teams"].items())
    ]})


def client_ip(ws: WebSocket) -> str:
    if TRUST_PROXY:
        fwd = ws.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


def too_soon(kind: str, key: str = "") -> bool:
    """True if the same host command was just handled (double-click guard)."""
    gap = DEBOUNCE.get(kind)
    if not gap:
        return False
    now = time.monotonic()
    k = (kind, key)
    if now - _last_cmd.get(k, -1e9) < gap:
        return True
    _last_cmd[k] = now
    return False


def ip_code_blocked(ip: str) -> bool:
    q = _ip_code_fails.get(ip)
    if not q:
        return False
    now = time.time()
    while q and q[0] < now - IP_WINDOW_SECS:
        q.popleft()
    return len(q) >= IP_MAX_CODE_FAILS


def ip_code_fail(ip: str) -> None:
    _ip_code_fails.setdefault(ip, deque()).append(time.time())


def save_state() -> None:
    """Atomic save: write a temp file, then swap it in, so a crash can't corrupt it."""
    data = {
        "round": state["round"],
        "teams": {n: {"score": t["score"], "code": t["code"]} for n, t in state["teams"].items()},
    }
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        print(f"[meme-off] could not save state: {e}")


def load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["round"] = max(1, int(data.get("round", 1)))
        changed = False
        for n, t in (data.get("teams") or {}).items():
            name = clean_name(n)
            if not name or name in state["teams"] or len(state["teams"]) >= MAX_TEAMS:
                continue
            if not isinstance(t, dict):
                t = {}
            try:
                score = int(t.get("score", 0))
            except (TypeError, ValueError):
                score = 0                                   # one damaged entry must not lose the rest
            code = clean_code(t.get("code"))
            if not valid_code(code) or code_in_use(code):
                code, changed = new_code(), True            # older save files had no codes
            state["teams"][name] = {"score": score, "code": code}
        if changed:
            save_state()
    except Exception as e:
        print(f"[meme-off] ignoring unreadable state file: {e}")
        try:
            os.replace(STATE_FILE, STATE_FILE.with_name(STATE_FILE.name + ".bad"))
        except OSError:
            pass


load_state()   # buzzer always starts locked with no buzzes after a restart


async def _send(conn: Conn, payload: str) -> bool:
    try:
        await asyncio.wait_for(conn.ws.send_text(payload), SEND_TIMEOUT)
        return True
    except Exception:
        return False


async def _close(conn: Conn) -> None:
    try:
        await asyncio.wait_for(conn.ws.close(), SEND_TIMEOUT)
    except Exception:
        pass


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def broadcast() -> None:
    """Send the current state to everyone who is inside (admitted team or host).
    Call while holding STATE_LOCK so updates always arrive in the order they happened.
    Sockets that haven't entered a valid code receive nothing."""
    state_json = state_payload()
    host_json = host_teams_payload()
    targets = [c for c in conns if c.team or c.is_host]

    async def push(c: Conn) -> bool:
        ok = await _send(c, state_json)
        if ok and c.is_host:
            ok = await _send(c, host_json)
        return ok

    results = await asyncio.gather(*(push(c) for c in targets))
    for c, ok in zip(targets, results):
        if not ok:
            conns.discard(c)
            spawn(_close(c))


async def kick_team(name: str, message: str) -> None:
    """Throw every device of this team back to the code screen."""
    for c in list(conns):
        if c.team == name:
            c.team = None
            await _send(c, _msg(type="kicked", msg=message))


async def _grace_lock(epoch: int) -> None:
    await asyncio.sleep(BUZZ_GRACE)
    async with STATE_LOCK:
        # Only lock if this is still the same question the buzz happened in.
        if state["epoch"] != epoch or state["locked"]:
            return
        state["locked"] = True
        await broadcast()


def _msg(**kw) -> str:
    return json.dumps(kw)


# ── routes ─────────────────────────────────────────────────────────────
NO_STORE = {"Cache-Control": "no-store"}


def _page(name: str) -> HTMLResponse:
    p = BASE_DIR / name
    if not p.exists():
        return HTMLResponse(f"<h1>{name} not found</h1>", status_code=404, headers=NO_STORE)
    return HTMLResponse(p.read_text(encoding="utf-8"), headers=NO_STORE)


@app.get("/", response_class=HTMLResponse)
async def team_page():
    return _page("index.html")


@app.get("/host", response_class=HTMLResponse)
async def host_page():
    return _page("host.html")


@app.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")


# ── host login ─────────────────────────────────────────────────────────
async def host_login(conn: Conn, msg: dict) -> None:
    ip = client_ip(conn.ws)
    now = time.time()
    rec = _login_fails.setdefault(ip, [0, 0.0])

    if rec[1] > now:
        wait = int(rec[1] - now) + 1
        await _send(conn, _msg(type="host_denied", msg=f"Too many attempts. Try again in {wait}s."))
        return

    supplied = str(msg.get("password", "")).encode("utf-8")
    if hmac.compare_digest(supplied, HOST_PASSWORD.encode("utf-8")):
        rec[0], rec[1] = 0, 0.0
        conn.is_host = True
        async with STATE_LOCK:
            await _send(conn, _msg(type="host_ok"))
            await _send(conn, state_payload())
            await _send(conn, host_teams_payload())
        return

    rec[0] += 1
    if rec[0] >= LOGIN_MAX_FAILS:
        rec[0], rec[1] = 0, now + LOGIN_LOCK_SECS
        await _send(conn, _msg(type="host_denied",
                               msg=f"Too many attempts. Locked for {LOGIN_LOCK_SECS}s."))
    else:
        await _send(conn, _msg(type="host_denied", msg="Wrong password. Try again."))


# ── team entry (the code gate) ─────────────────────────────────────────
async def team_join(conn: Conn, msg: dict) -> None:
    now = time.time()
    if conn.cooldown_until > now:
        wait = int(conn.cooldown_until - now) + 1
        await _send(conn, _msg(type="join_error", msg=f"Too many wrong codes. Wait {wait}s."))
        return
    ip = client_ip(conn.ws)
    if ip_code_blocked(ip):
        await _send(conn, _msg(type="join_error", msg="Too many wrong codes from this network. Wait a minute."))
        return

    code = clean_code(msg.get("code"))
    if not code:
        await _send(conn, _msg(type="join_error", msg="Enter your team code."))
        return

    async with STATE_LOCK:
        name = find_team_by_code(code)
        if name is None:
            conn.code_fails += 1
            ip_code_fail(ip)
            if conn.code_fails >= CODE_MAX_FAILS:
                conn.code_fails = 0
                conn.cooldown_until = now + CODE_COOLDOWN_SECS
                await _send(conn, _msg(type="join_error",
                                       msg=f"Wrong code. Locked for {CODE_COOLDOWN_SECS}s."))
            else:
                await _send(conn, _msg(type="join_error", msg="That code isn't valid."))
            return
        if conn.team and conn.team != name:
            await _send(conn, _msg(type="join_error",
                                   msg=f"This device is already playing as {conn.team}."))
            return
        conn.code_fails = 0
        conn.team = name
        await _send(conn, _msg(type="joined", team=name))
        await broadcast()          # also tells the host this team is online


# ── message handling ───────────────────────────────────────────────────
HOST_ONLY = {"unlock", "lock", "reset", "next_round", "score", "remove_team",
             "add_teams", "set_code", "regen_code"}


async def handle(conn: Conn, msg: dict) -> None:
    kind = msg.get("type")

    if kind == "host_auth":
        await host_login(conn, msg)
        return

    if kind == "join":
        if not conn.is_host:
            await team_join(conn, msg)
        return

    # ---- team buzz (always as the team this socket was admitted as) ----
    if kind == "buzz":
        async with STATE_LOCK:
            team = conn.team
            if (state["locked"] or not team or team not in state["teams"]
                    or team in state["buzz_order"]):
                return
            state["buzz_order"].append(team)
            if len(state["buzz_order"]) == 1:          # first buzz starts the lock-out
                if BUZZ_GRACE > 0:
                    spawn(_grace_lock(state["epoch"]))
                else:
                    state["locked"] = True
            await broadcast()
        return

    # ---- everything below is host-only ----
    if kind not in HOST_ONLY:
        return
    if not conn.is_host:
        await _send(conn, _msg(type="host_denied", msg="Host login required."))
        return

    team_arg = clean_name(msg.get("team")) if kind in ("score", "remove_team", "set_code", "regen_code") else ""
    if too_soon(kind, team_arg):
        return

    async with STATE_LOCK:
        notice = None

        if kind == "unlock":
            if not state["locked"]:
                return                                  # already open: never wipe live buzzes
            state["epoch"] += 1
            state["buzz_order"] = []
            state["locked"] = False

        elif kind == "lock":
            if state["locked"]:
                return
            state["epoch"] += 1
            state["locked"] = True                      # keeps any buzzes already recorded

        elif kind == "reset":
            state["epoch"] += 1
            state["buzz_order"] = []
            state["locked"] = True

        elif kind == "next_round":
            state["epoch"] += 1
            state["round"] += 1
            state["buzz_order"] = []
            state["locked"] = True
            save_state()

        elif kind == "score":
            try:
                delta = int(msg.get("delta", 0))
            except (TypeError, ValueError):
                return
            if team_arg not in state["teams"] or delta == 0 or abs(delta) > MAX_SCORE_STEP:
                return
            state["teams"][team_arg]["score"] += delta
            save_state()

        elif kind == "remove_team":
            if team_arg not in state["teams"]:
                return
            del state["teams"][team_arg]
            if team_arg in state["buzz_order"]:
                state["buzz_order"].remove(team_arg)
            save_state()
            await kick_team(team_arg, "Your team was removed by the host.")

        elif kind == "add_teams":
            entries = msg.get("entries")
            if not isinstance(entries, list):
                return
            added, skipped = 0, []
            for e in entries[:MAX_ADD_BATCH]:
                if not isinstance(e, dict):
                    continue
                name = clean_name(e.get("name"))
                if not name:
                    continue
                if name in state["teams"]:
                    skipped.append(f"{name} (name already exists)")
                    continue
                if len(state["teams"]) >= MAX_TEAMS:
                    skipped.append(f"{name} (team limit reached)")
                    continue
                raw_code = clean_code(e.get("code"))
                if raw_code:
                    if not valid_code(raw_code):
                        skipped.append(f"{name} (code must be {MIN_CODE_LEN}-{MAX_CODE_LEN} letters/numbers)")
                        continue
                    if code_in_use(raw_code):
                        skipped.append(f"{name} (code already used)")
                        continue
                    code = raw_code
                else:
                    code = new_code()
                state["teams"][name] = {"score": 0, "code": code}
                added += 1
            if added:
                save_state()
            text = f"Added {added} team{'s' if added != 1 else ''}."
            if skipped:
                text += " Skipped: " + "; ".join(skipped[:6]) + ("…" if len(skipped) > 6 else "")
            notice = _msg(type="host_notice", level="warn" if skipped else "ok", msg=text)

        elif kind in ("set_code", "regen_code"):
            if team_arg not in state["teams"]:
                return
            if kind == "regen_code":
                code = new_code()
            else:
                code = clean_code(msg.get("code"))
                if not valid_code(code):
                    await _send(conn, _msg(type="host_notice", level="warn",
                                           msg=f"Code must be {MIN_CODE_LEN}-{MAX_CODE_LEN} letters/numbers."))
                    return
                if code_in_use(code, ignore_team=team_arg):
                    await _send(conn, _msg(type="host_notice", level="warn", msg="That code is already used by another team."))
                    return
            state["teams"][team_arg]["code"] = code
            save_state()
            await kick_team(team_arg, "Your team code was changed. Enter the new code.")
            notice = _msg(type="host_notice", level="ok", msg=f"New code for {team_arg}: {code}")

        await broadcast()
        if notice:
            await _send(conn, notice)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    conn = Conn(ws)
    conns.add(conn)          # a fresh socket gets NOTHING until it enters a valid code / host password
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if raw is None or len(raw) > MAX_MSG_CHARS:
                continue
            if not conn.allow():
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            try:
                await handle(conn, msg)
            except Exception as e:                      # one bad message must never kill the socket
                print(f"[meme-off] error handling {msg.get('type')!r}: {e!r}")
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        conns.discard(conn)
        if conn.team or conn.is_host:                   # presence changed: refresh the host's online dots
            try:
                async with STATE_LOCK:
                    await broadcast()
            except Exception:
                pass
