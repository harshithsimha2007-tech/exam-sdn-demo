#!/usr/bin/env python3
"""Multi-threaded TCP online exam server.
Protocol (JSON lines): JOIN -> START(questions) -> ANSWER/ACK ... -> SUBMIT -> RESULT.
Server enforces a per-student timer. Notifies the SDN controller of events via UDP broadcast
(the switch punts it to the controller as a packet-in: in-band app->SDN signalling)."""
import socket, threading, json, time, argparse, csv, os

from common import Conn

EVENT_PORT = 9999
lock = threading.Lock()
active = set()

def notify(ev, **kw):
    """App event -> SDN controller (UDP broadcast, intercepted by the switch -> controller)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(json.dumps(dict(ev=ev, ts=time.time(), **kw)).encode(),
                 (ARGS.event_addr, EVENT_PORT))
        s.close()
    except OSError as e:
        print(f"[warn] event not sent: {e}")

def grade(answers):
    return sum(1 for q in QUESTIONS if answers.get(str(q["id"])) == q["answer"])

def handle(sock, addr):
    c = Conn(sock)
    name = None
    try:
        sock.settimeout(30)
        m = c.recv()
        if m.get("type") != "JOIN" or not m.get("name"):
            c.send({"type": "ERROR", "msg": "expected JOIN with name"}); return
        name = m["name"]
        with lock:
            if name in active:
                c.send({"type": "ERROR", "msg": "name already in use"}); name = None; return
            active.add(name)
        public = [{"id": q["id"], "q": q["q"], "options": q["options"]} for q in QUESTIONS]
        start = time.time(); deadline = start + ARGS.duration
        c.send({"type": "START", "duration": ARGS.duration, "questions": public})
        print(f"[+] {name} {addr[0]} started")
        notify("EXAM_START", student=name, ip=addr[0])

        answers, timed_out = {}, False
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                timed_out = True; break
            sock.settimeout(remaining)
            try:
                m = c.recv()
            except socket.timeout:
                timed_out = True; break
            t = m.get("type")
            if t == "ANSWER":
                answers[str(m["qid"])] = m["ans"]
                c.send({"type": "ACK", "qid": m["qid"], "remaining": round(deadline - time.time(), 1)})
            elif t == "SUBMIT":
                break
        score = grade(answers); taken = round(time.time() - start, 2)
        c.send({"type": "RESULT", "score": score, "total": len(QUESTIONS),
                "timed_out": timed_out, "time_taken": taken})
        print(f"[=] {name}: {score}/{len(QUESTIONS)} timeout={timed_out} {taken}s")
        notify("EXAM_END", student=name, ip=addr[0], score=score, timed_out=timed_out)
        with lock, open("logs/results.csv", "a", newline="") as f:
            csv.writer(f).writerow([name, addr[0], score, len(QUESTIONS), timed_out, taken])
    except (ConnectionError, OSError, json.JSONDecodeError) as e:
        print(f"[!] {name or addr}: {e}")
    finally:
        with lock:
            active.discard(name)
        sock.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--duration", type=int, default=120, help="exam length in seconds")
    p.add_argument("--questions", default="questions.json")
    p.add_argument("--event-addr", default=os.environ.get("EVENT_ADDR", "10.255.255.255"))
    ARGS = p.parse_args()
    QUESTIONS = json.load(open(ARGS.questions))
    os.makedirs("logs", exist_ok=True)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((ARGS.host, ARGS.port)); srv.listen(128)
    print(f"Exam server on {ARGS.host}:{ARGS.port}, {len(QUESTIONS)} questions, {ARGS.duration}s")
    while True:
        s, a = srv.accept()
        threading.Thread(target=handle, args=(s, a), daemon=True).start()
