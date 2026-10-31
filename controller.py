"""Ryu OpenFlow 1.3 controller for the online exam network.
 - L2 learning switch; exam traffic (TCP :5000) gets dedicated per-flow rules (priority 10)
   so it can be counted/monitored separately.
 - Intercepts app events (UDP :9999 sent by the exam server) -> socket/SDN integration.
 - Polls flow stats every 5s: per-student bytes, rate and Jain's fairness index."""
import json, time, csv, os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, tcp, udp, ether_types
from ryu.lib import hub

EXAM_PORT, EVENT_PORT, POLL = 5000, 9999, 5
PRIO_EXAM, PRIO_EVENT, PRIO_L2 = 10, 50, 1

class ExamController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mac_to_port = {}
        self.dps = {}
        self.prev = {}          # (dpid, src, dst) -> bytes at last poll
        self.students = {}      # ip -> name (from app events)
        os.makedirs("logs", exist_ok=True)
        hub.spawn(self._poll)

    # ---------- switch setup ----------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath; p = dp.ofproto_parser; o = dp.ofproto
        self.dps[dp.id] = dp
        cpu = [p.OFPActionOutput(o.OFPP_CONTROLLER, o.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, p.OFPMatch(), cpu)                                   # table-miss
        self.add_flow(dp, PRIO_EVENT, p.OFPMatch(eth_type=0x0800, ip_proto=17,
                                                 udp_dst=EVENT_PORT), cpu)        # app events
        self.logger.info("Switch %s connected", dp.id)

    def add_flow(self, dp, prio, match, actions, idle=0):
        p = dp.ofproto_parser; o = dp.ofproto
        inst = [p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=prio, match=match,
                                 instructions=inst, idle_timeout=idle))

    # ---------- packet-in ----------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg; dp = msg.datapath; o = dp.ofproto; p = dp.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        ip = pkt.get_protocol(ipv4.ipv4)
        u = pkt.get_protocol(udp.udp)
        if u and u.dst_port == EVENT_PORT:                  # application event
            self.handle_app_event(dp.id, pkt.protocols[-1])
            return

        self.mac_to_port.setdefault(dp.id, {})[eth.src] = in_port
        out = self.mac_to_port[dp.id].get(eth.dst, o.OFPP_FLOOD)
        actions = [p.OFPActionOutput(out)]
        if out != o.OFPP_FLOOD:
            t = pkt.get_protocol(tcp.tcp)
            if ip and t and EXAM_PORT in (t.src_port, t.dst_port):
                kw = dict(eth_type=0x0800, ipv4_src=ip.src, ipv4_dst=ip.dst, ip_proto=6)
                if t.dst_port == EXAM_PORT: kw["tcp_dst"] = EXAM_PORT
                else:                       kw["tcp_src"] = EXAM_PORT
                self.add_flow(dp, PRIO_EXAM, p.OFPMatch(**kw), actions, idle=30)
            else:
                self.add_flow(dp, PRIO_L2, p.OFPMatch(in_port=in_port, eth_dst=eth.dst,
                                                      eth_src=eth.src), actions, idle=60)
        data = msg.data if msg.buffer_id == o.OFP_NO_BUFFER else None
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                   actions=actions, data=data))

    def handle_app_event(self, dpid, payload):
        try:
            e = json.loads(payload.decode())
        except Exception:
            return
        if e["ev"] == "EXAM_START":
            self.students[e["ip"]] = e["student"]
        self.logger.info("APP EVENT via s%s: %s", dpid, e)
        # D2 hook: react here (e.g. prioritise exam flows / meter others / block unregistered hosts)

    # ---------- monitoring ----------
    def _poll(self):
        while True:
            hub.sleep(POLL)
            for dp in list(self.dps.values()):
                dp.send_msg(dp.ofproto_parser.OFPFlowStatsRequest(dp))

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def stats_reply(self, ev):
        dpid = ev.msg.datapath.id
        per_src = {}
        for s in ev.msg.body:
            if s.priority != PRIO_EXAM: continue
            src = s.match.get("ipv4_src"); dst = s.match.get("ipv4_dst")
            if "tcp_dst" not in s.match: continue          # only student->server direction
            key = (dpid, src, dst)
            delta = s.byte_count - self.prev.get(key, 0)
            self.prev[key] = s.byte_count
            per_src[src] = per_src.get(src, 0) + delta / POLL     # B/s
        if not per_src: return
        rates = list(per_src.values())
        jain = (sum(rates) ** 2) / (len(rates) * sum(x * x for x in rates)) if any(rates) else 1.0
        self.logger.info("[s%s] exam traffic (B/s): %s | Jain fairness=%.3f", dpid,
                         {f"{self.students.get(k, '?')}@{k}": round(v) for k, v in per_src.items()}, jain)
        with open("logs/traffic_log.csv", "a", newline="") as f:
            for k, v in per_src.items():
                csv.writer(f).writerow([round(time.time(), 1), dpid, k, round(v), round(jain, 3)])
