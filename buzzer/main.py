from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import time
import json

app = FastAPI()

# ── GAME STATE ──
state = {
    "teams": {},        # team_name: {score, buzzed_at, rank}
    "locked": True,     # buzzer locked or open
    "buzz_order": [],   # list of team names in order they buzzed
    "timer": 0,         # countdown seconds
    "round": 1,         # current round number
}

# All connected WebSocket clients
connections = []

# ── HELPER: send state to everyone ──
async def broadcast(data: dict):
    message = json.dumps(data)
    dead = []
    for ws in connections:
        try:
            await ws.send_text(message)
        except:
            dead.append(ws)
    for ws in dead:
        connections.remove(ws)

# ── WEBSOCKET ENDPOINT ──
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    
    # Send current state to new connection
    await websocket.send_text(json.dumps({
        "type": "state",
        "state": state
    }))
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            # Team joins
            if msg_type == "join":
                team_name = message.get("team")
                if team_name and team_name not in state["teams"]:
                    state["teams"][team_name] = {
                        "score": 0,
                        "buzzed_at": None,
                        "rank": None
                    }
                await broadcast({"type": "state", "state": state})

            # Team buzzes
            elif msg_type == "buzz":
                team_name = message.get("team")
                if (not state["locked"] and 
                    team_name in state["teams"] and 
                    team_name not in state["buzz_order"]):
                    
                    state["teams"][team_name]["buzzed_at"] = time.time()
                    state["buzz_order"].append(team_name)
                    state["teams"][team_name]["rank"] = len(state["buzz_order"])
                    
                    # Lock after first buzz
                    if len(state["buzz_order"]) == 1:
                        state["locked"] = True
                    
                    await broadcast({"type": "state", "state": state})

            # Host unlocks buzzer
            elif msg_type == "unlock":
                state["locked"] = False
                state["buzz_order"] = []
                for team in state["teams"]:
                    state["teams"][team]["buzzed_at"] = None
                    state["teams"][team]["rank"] = None
                await broadcast({"type": "state", "state": state})

            # Host resets everything
            elif msg_type == "reset":
                state["buzz_order"] = []
                state["locked"] = True
                for team in state["teams"]:
                    state["teams"][team]["buzzed_at"] = None
                    state["teams"][team]["rank"] = None
                await broadcast({"type": "state", "state": state})

            # Host updates score
            elif msg_type == "score":
                team_name = message.get("team")
                delta = message.get("delta", 0)
                if team_name in state["teams"]:
                    state["teams"][team_name]["score"] += delta
                await broadcast({"type": "state", "state": state})

            # Host sets timer
            elif msg_type == "timer":
                state["timer"] = message.get("seconds", 30)
                await broadcast({"type": "state", "state": state})

            # Host advances round
            elif msg_type == "next_round":
                state["round"] += 1
                state["buzz_order"] = []
                state["locked"] = True
                for team in state["teams"]:
                    state["teams"][team]["buzzed_at"] = None
                    state["teams"][team]["rank"] = None
                await broadcast({"type": "state", "state": state})

            # Host removes a team
            elif msg_type == "remove_team":
                team_name = message.get("team")
                if team_name in state["teams"]:
                    del state["teams"][team_name]
                await broadcast({"type": "state", "state": state})

    except WebSocketDisconnect:
        connections.remove(websocket)

# ── SERVE HTML FILES ──
@app.get("/")
async def get_team_view():
    with open("index.html") as f:
        return HTMLResponse(f.read())

@app.get("/host")
async def get_host_view():
    with open("host.html") as f:
        return HTMLResponse(f.read())