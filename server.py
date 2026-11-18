from http.server import SimpleHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import subprocess, os, json, threading

lock = threading.Lock()

subprocess.run(["gcc", "-O2", "ludo.c", "-o", "ludo"])
if not os.path.exists("state.txt"):
    subprocess.run(["./ludo", "r", "2"])  # Default to 2-player ready

SEATS_FILE = "seats.json"

def load_seats():
    if os.path.exists(SEATS_FILE):
        with open(SEATS_FILE, "r") as f:
            return json.load(f)
    return {"host": None, "players": {}}  # players maps seat_idx ("0"-"3") -> {"id": pid, "name": name}

def save_seats(data):
    with open(SEATS_FILE, "w") as f:
        json.dump(data, f)

def read_game_state():
    with open("state.txt", "r") as f:
        lines = [line.strip() for line in f.readlines()]
    header = list(map(int, lines[0].split()))
    active_seats = list(map(int, lines[1].split()))
    tokens = [list(map(int, lines[i + 2].split())) for i in range(4)]
    status = lines[6] if len(lines) > 6 else ""
    return {
        "turn": header[0],
        "dice": header[1],
        "sixCount": header[2],
        "winner": header[3],
        "numPlayers": header[4],
        "activeSeats": active_seats,
        "tokens": tokens,
        "status": status
    }

class LudoHandler(SimpleHTTPRequestHandler):
    def send_json(self, payload, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        pid = qs.get("pid", [""])[0]

        with lock:
            seats_data = load_seats()
            state = read_game_state()

            if path == "/state":
                # Identify what seat (if any) this pid occupies
                my_seat = None
                for s_idx, info in seats_data["players"].items():
                    if info["id"] == pid:
                        my_seat = int(s_idx)
                        break

                public_players = {
                    s_idx: info["name"] for s_idx, info in seats_data["players"].items()
                }
                self.send_json({
                    **state,
                    "mySeat": my_seat,
                    "isHost": (seats_data["host"] == pid and pid != ""),
                    "hasHost": (seats_data["host"] is not None),
                    "players": public_players
                })

            elif path == "/action/join":
                seat_str = qs.get("seat", [""])[0]
                name = qs.get("name", ["Player"])[0][:16] or "Player"
                if seat_str in ["0", "1", "2", "3"] and pid:
                    seat_int = int(seat_str)
                    if state["activeSeats"][seat_int] == 1:
                        # Remove pid from any previous seat
                        for k in list(seats_data["players"].keys()):
                            if seats_data["players"][k]["id"] == pid:
                                del seats_data["players"][k]
                        # Claim seat if empty
                        if seat_str not in seats_data["players"]:
                            seats_data["players"][seat_str] = {"id": pid, "name": name}
                            if not seats_data["host"]:
                                seats_data["host"] = pid
                            save_seats(seats_data)
                self.send_json({"ok": True})

            elif path == "/action/leave":
                for k in list(seats_data["players"].keys()):
                    if seats_data["players"][k]["id"] == pid:
                        del seats_data["players"][k]
                save_seats(seats_data)
                self.send_json({"ok": True})

            elif path == "/action/roll":
                turn_str = str(state["turn"])
                occupant = seats_data["players"].get(turn_str)
                if occupant and occupant["id"] == pid:
                    subprocess.run(["./ludo", "d"])
                self.send_json({"ok": True})

            elif path.startswith("/action/move_"):
                turn_str = str(state["turn"])
                occupant = seats_data["players"].get(turn_str)
                if occupant and occupant["id"] == pid:
                    token_id = path.split("_")[1]
                    if token_id in ["0", "1", "2", "3"]:
                        subprocess.run(["./ludo", "m", token_id])
                self.send_json({"ok": True})

            elif path == "/action/reset":
                # Only host (or anyone if no host exists yet) can reconfigure/reset
                if not seats_data["host"] or seats_data["host"] == pid:
                    count = qs.get("players", ["2"])[0]
                    if count not in ["2", "3", "4"]:
                        count = "2"
                    subprocess.run(["./ludo", "r", count])
                    seats_data["host"] = pid
                    seats_data["players"] = {}  # Clear seats for fresh match setup
                    save_seats(seats_data)
                self.send_json({"ok": True})

            else:
                super().do_GET()

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Multiplayer Ludo Server running at http://localhost:{port}")
    HTTPServer(("0.0.0.0", port), LudoHandler).serve_forever()
