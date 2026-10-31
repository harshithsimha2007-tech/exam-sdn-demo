#!/usr/bin/env python3
"""Mininet topology:  h1(server) - s1 ===(bottleneck)=== s2 - h2..hN (students)
Usage: sudo python3 topology.py [--students 5] [--bw 10] [--autotest] [--duration 120]"""
import argparse, time, os
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

ap = argparse.ArgumentParser()
ap.add_argument("--students", type=int, default=5)
ap.add_argument("--bw", type=float, default=10, help="bottleneck s1-s2 bandwidth (Mbps)")
ap.add_argument("--duration", type=int, default=120)
ap.add_argument("--autotest", action="store_true", help="launch all clients automatically")
A = ap.parse_args()

setLogLevel("info")
net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)
net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)
s1, s2 = net.addSwitch("s1", protocols="OpenFlow13"), net.addSwitch("s2", protocols="OpenFlow13")
server = net.addHost("h1", ip="10.0.0.1/8")
studs = [net.addHost(f"h{i+2}", ip=f"10.0.0.{i+2}/8") for i in range(A.students)]
net.addLink(server, s1, bw=100)
net.addLink(s1, s2, bw=A.bw)                    # bottleneck for congestion tests
for h in studs:
    net.addLink(h, s2, bw=100)
net.start()
time.sleep(3)
info("*** connectivity check\n"); net.pingAll()

os.makedirs("logs", exist_ok=True)
server.cmd(f"python3 exam_server.py --duration {A.duration} > logs/server.log 2>&1 &")
time.sleep(1)
info("*** exam server running on h1 (10.0.0.1:5000)\n")

if A.autotest:
    for h in studs:
        h.cmd(f"python3 exam_client.py --name {h.name} --auto > logs/{h.name}.log 2>&1 &")
    info("*** auto clients launched; see logs/*.log\n")
else:
    info("*** In CLI run e.g.:  h2 python3 exam_client.py --name alice\n")
CLI(net)
net.stop()
