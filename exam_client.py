#!/usr/bin/env python3
"""Exam client. Interactive by default; --auto answers randomly (for load / congestion tests)."""
import socket, argparse, time, random, select, sys, csv, os
from common import Conn

p = argparse.ArgumentParser()
p.add_argument("--host", default="10.0.0.1")
p.add_argument("--port", type=int, default=5000)
p.add_argument("--name", required=True)
p.add_argument("--auto", action="store_true")
p.add_argument("--think", type=float, default=1.0, help="max think time per question (auto)")
A = p.parse_args()

s = socket.create_connection((A.host, A.port), timeout=10)
s.settimeout(None)
c = Conn(s)
t_conn = time.time()
c.send({"type": "JOIN", "name": A.name})
m = c.recv()
if m["type"] == "ERROR":
    print("Server:", m["msg"]); sys.exit(1)
start_latency = time.time() - t_conn
print(f"Exam started. Duration {m['duration']}s, {len(m['questions'])} questions.")
rtts, result = [], None

for q in m["questions"]:
    print(f"\nQ{q['id']}. {q['q']}")
    for k, v in q["options"].items():
        print(f"  {k}) {v}")
    if A.auto:
        time.sleep(random.uniform(0, A.think))
        ans = random.choice(list(q["options"]))
    else:
        print("Your answer: ", end="", flush=True)
        r, _, _ = select.select([sys.stdin, s], [], [])
        if s in r:                      # server pushed RESULT (timer expired)
            result = c.recv(); break
        ans = sys.stdin.readline().strip().upper()
    t0 = time.time()
    c.send({"type": "ANSWER", "qid": q["id"], "ans": ans})
    r = c.recv()
    if r["type"] == "RESULT":
        result = r; break
    rtts.append(time.time() - t0)
    print(f"  [ack, {r['remaining']}s left]")

if result is None:
    c.send({"type": "SUBMIT"})
    result = c.recv()
    while result["type"] != "RESULT":
        result = c.recv()

print(f"\n=== RESULT: {result['score']}/{result['total']}  "
      f"(timed out: {result['timed_out']}, time: {result['time_taken']}s) ===")
if rtts:
    avg = sum(rtts) / len(rtts)
    print(f"avg answer RTT: {avg*1000:.1f} ms")
    os.makedirs("logs", exist_ok=True)
    with open("logs/client_metrics.csv", "a", newline="") as f:
        csv.writer(f).writerow([A.name, round(start_latency, 4), round(avg, 4), round(max(rtts), 4)])
s.close()
