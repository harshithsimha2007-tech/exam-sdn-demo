# SDN-Based Multi-User Online Examination System (Jackfruit Mini Project)

TCP socket exam application (server on h1, students on h2..hN) running in Mininet, managed/monitored by a Ryu OpenFlow 1.3 controller.

## Architecture
```
 h1 (exam server :5000) -- s1 ==10Mbps bottleneck== s2 -- h2..hN (students)
                            \_______ Ryu controller (127.0.0.1:6633) _______/
```
- **Protocol**: JSON lines over TCP. `JOIN -> START(questions) -> ANSWER/ACK ... -> SUBMIT -> RESULT`
- **Concurrency**: one thread per client; per-student timer enforced server-side (socket timeout = remaining time).
- **SDN**: learning switch + dedicated priority-10 flow rules for TCP:5000, 5s flow-stats polling, Jain's fairness index.
- **Socket<->SDN integration**: server sends UDP event (port 9999, broadcast) at exam start/end; the switch punts it to the controller (packet-in) which logs it and maps IP -> student.

## Setup (Ubuntu)
```
sudo apt install mininet openvswitch-switch python3-pip
pip3 install ryu eventlet==0.30.2     # Python <=3.9 recommended for Ryu
```
## Run
```
# Terminal 1
ryu-manager controller.py
# Terminal 2
sudo mn -c
sudo python3 topology.py --students 5 --autotest        # automatic
sudo python3 topology.py --students 3                    # manual; then in CLI:
mininet> h2 python3 exam_client.py --name alice
```
## Test cases (D1)
1. `pingall` -> 0% loss.  2. One client completes exam, result correct.  3. 5 concurrent clients (`--autotest`).
4. Timer: start client, wait > duration -> server pushes RESULT with timed_out=true (`--duration 20` to speed up).
5. Controller log shows APP EVENT lines and per-student exam traffic + fairness. `mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s2`
## Congestion test (D2 prep)
```
mininet> h1 iperf -s &
mininet> h3 iperf -c 10.0.0.1 -t 60 &      # saturates the 10 Mbps link
```
then compare `logs/client_metrics.csv` (RTT) with/without congestion.
