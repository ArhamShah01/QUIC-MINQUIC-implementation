"""Tests that MINBBR is actually the congestion controller aioquic uses."""
import math

import pytest
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.reno import RenoCongestionControl

from minquic.congestion import (
    MAX_DRAIN_ROUNDS,
    PROBE_BW_CWND_GAINS,
    MinBbrCongestionControl,
)
from minquic.connection import create_quic_configuration as minquic_configuration
from quic.connection import create_quic_configuration as quic_configuration


class FakePacket:
    def __init__(self, packet_number: int, sent_bytes: int = 1000, sent_time: float = 0.0):
        self.epoch = 3
        self.packet_number = packet_number
        self.sent_bytes = sent_bytes
        self.sent_time = sent_time


def run_round(cc, first_pn, now, rtt, packets=10):
    """Send ``packets`` packets at ``now`` and ack them all ``rtt`` later."""
    sent = [FakePacket(first_pn + i, sent_time=now) for i in range(packets)]
    for packet in sent:
        cc.on_packet_sent(packet=packet)
    for packet in sent:
        cc.on_packet_acked(now=now + rtt, packet=packet)
    cc.on_rtt_measurement(now=now + rtt, rtt=rtt)
    return first_pn + packets


def test_minquic_connection_uses_minbbr():
    conn = QuicConnection(configuration=minquic_configuration(is_client=True))
    assert isinstance(conn._loss._cc, MinBbrCongestionControl)


def test_quic_baseline_uses_reno():
    conn = QuicConnection(configuration=quic_configuration(is_client=True))
    assert isinstance(conn._loss._cc, RenoCongestionControl)


def test_bytes_in_flight_accounting():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    packets = [FakePacket(i) for i in range(3)]
    for packet in packets:
        cc.on_packet_sent(packet=packet)
    assert cc.bytes_in_flight == 3000
    cc.on_packet_acked(now=1.0, packet=packets[0])
    cc.on_packets_expired(packets=[packets[1]])
    cc.on_packets_lost(now=1.0, packets=[packets[2]])
    assert cc.bytes_in_flight == 0
    assert cc._packet_state == {}


def run_until_probe_bw(cc, pn, now, rtt=0.05):
    """Run steady rounds until MINBBR leaves STARTUP/DRAIN for PROBE_BW."""
    for _ in range(20):
        if cc.state == "PROBE_BW":
            break
        pn = run_round(cc, pn, now=now, rtt=rtt)
        now += 0.1
    assert cc.state == "PROBE_BW"
    return pn, now


def test_btl_bw_is_measured_delivery_rate():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    # 10 x 1000 bytes delivered in 50 ms -> 200,000 bytes/s.
    run_round(cc, 0, now=0.0, rtt=0.05)
    assert cc.btl_bw == 10_000 / 0.05
    assert cc.rtprop == 0.05
    assert cc.bdp == cc.btl_bw * cc.rtprop
    assert cc.state == "STARTUP"


def test_startup_grows_window_by_acked_bytes():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    initial = cc.congestion_window
    run_round(cc, 0, now=0.0, rtt=0.05)
    assert cc.congestion_window == initial + 10_000


def test_startup_exits_when_bandwidth_plateaus():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = 0, 0.0
    # Constant delivery rate: BtlBW stops growing, so STARTUP ends after
    # FULL_BW_ROUNDS rounds, DRAIN empties, and PROBE_BW starts in DOWN.
    rounds = 0
    while cc.state == "STARTUP" and rounds < 10:
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
        rounds += 1
    assert rounds > 3  # needs 3 rounds without 25% BtlBW growth
    # This round's remaining ACKs empty the pipe, so DRAIN ends immediately.
    assert cc.state == "PROBE_BW"
    assert cc.probe_bw_phase == "DOWN"


def test_probe_bw_cycles_through_phases():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = run_until_probe_bw(cc, 0, 0.0)
    seen = [cc.probe_bw_phase]
    for _ in range(9):
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
        seen.append(cc.probe_bw_phase)
    assert seen == ["DOWN", "CRUISE", "CRUISE", "CRUISE", "CRUISE", "CRUISE",
                    "CRUISE", "REFILL", "UP", "DOWN"]
    assert cc.probe_bw_version == "MINBBR"


def test_probe_bw_window_gain_follows_phase():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    run_until_probe_bw(cc, 0, 0.0)
    gains = PROBE_BW_CWND_GAINS["MINBBR"]
    for phase in ("UP", "CRUISE", "DOWN"):
        cc.probe_bw_phase = phase
        assert cc.get_congestion_window() == max(int(cc.bdp * gains[phase]), 4 * 1200)
    assert gains["UP"] > gains["CRUISE"] > gains["DOWN"]


def test_algorithm2_switches_to_bbrv2_and_back():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = run_until_probe_bw(cc, 0, 0.0)
    # Queueing from a competitor: every round's MinRTT is well above RTprop.
    # After THETA_R1 = 2 ProbeCruise sub-states, switch to BBRv2 and restart.
    for _ in range(30):
        pn = run_round(cc, pn, now=now, rtt=0.08)
        now += 0.1
        if cc.probe_bw_version == "BBRV2":
            break
    assert cc.probe_bw_version == "BBRV2"
    assert cc.state == "STARTUP"

    # Competitor gone: MinRTT back near RTprop for THETA_R2 = 4 cruises.
    pn, now = run_until_probe_bw(cc, pn, now)
    for _ in range(60):
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
        if cc.probe_bw_version == "MINBBR":
            break
    assert cc.probe_bw_version == "MINBBR"
    assert cc.state == "PROBE_BW"


def test_probe_rtt_after_rtprop_expires():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = run_until_probe_bw(cc, 0, 0.0)
    # No RTT sample at or below RTprop for more than 10 s.
    now += 11.0
    pn = run_round(cc, pn, now=now, rtt=0.06)
    pn = run_round(cc, pn, now=now + 0.1, rtt=0.06)
    assert cc.state == "PROBE_RTT"
    assert cc.congestion_window == 4 * 1200
    # After PROBE_RTT_DURATION with little in flight, return to PROBE_BW.
    run_round(cc, pn, now=now + 0.5, rtt=0.06)
    assert cc.state == "PROBE_BW"


def test_min_btlbw_filter_drops_oldest_sample_on_jitter():
    def run(jitter_rtt):
        cc = MinBbrCongestionControl(max_datagram_size=1200)
        pn = run_round(cc, 0, now=0.0, rtt=0.05)
        pn = run_round(cc, pn, now=0.1, rtt=0.05)
        pn = run_round(cc, pn, now=0.2, rtt=jitter_rtt)
        run_round(cc, pn, now=0.5, rtt=0.05)
        return cc

    steady, jittered = run(0.05), run(0.2)
    # Without jitter nothing is evicted inside the 10-round window.
    assert steady.btl_bw_filter[0][0] == 0
    # A round whose min RTT exceeds k * RTprop evicts the oldest sample.
    assert len(jittered.btl_bw_filter) == len(steady.btl_bw_filter) - 1
    assert jittered.btl_bw_filter[0][0] == 1


def test_btl_bw_filter_window_expires_old_samples():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05)
    fast = cc.btl_bw
    now = 0.1
    for _ in range(12):
        pn = run_round(cc, pn, now=now, rtt=0.05, packets=2)
        now += 0.1
    assert cc.btl_bw < fast


def run_round_with_loss(cc, first_pn, now, rtt, packets=10, lost=0):
    """Send ``packets``; the first ``lost`` are declared lost, the rest acked."""
    sent = [FakePacket(first_pn + i, sent_time=now) for i in range(packets)]
    for packet in sent:
        cc.on_packet_sent(packet=packet)
    if lost:
        cc.on_packets_lost(now=now + rtt, packets=sent[:lost])
    for packet in sent[lost:]:
        cc.on_packet_acked(now=now + rtt, packet=packet)
    cc.on_rtt_measurement(now=now + rtt, rtt=rtt)
    return first_pn + packets


def test_loss_below_threshold_is_ignored():
    """Jitter makes late packets look lost; a trickle must not cap bandwidth."""
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05, packets=100)
    # 1 of 100 packets = 1%, below LOSS_RATE_THRESHOLD.
    pn = run_round_with_loss(cc, pn, now=0.1, rtt=0.05, packets=100, lost=1)
    pn = run_round(cc, pn, now=0.2, rtt=0.05, packets=100)
    assert cc.bw_lo == math.inf
    assert cc.model_bw == cc.btl_bw


def test_loss_above_threshold_caps_bandwidth():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05, packets=100)
    pn = run_round_with_loss(cc, pn, now=0.1, rtt=0.05, packets=100, lost=20)
    btl_bw = cc.btl_bw
    # The response is applied at the end of the round that saw the loss.
    run_round(cc, pn, now=0.2, rtt=0.05, packets=100)
    assert cc.bw_lo == pytest.approx(btl_bw * 0.8)
    assert cc.bdp == pytest.approx(cc.model_bw * cc.rtprop)


def test_heavy_loss_in_startup_ends_startup():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05, packets=100)
    assert cc.state == "STARTUP"
    pn = run_round_with_loss(cc, pn, now=0.1, rtt=0.05, packets=100, lost=30)
    run_round(cc, pn, now=0.2, rtt=0.05, packets=100)
    assert cc.state in ("DRAIN", "PROBE_BW")
    assert cc._full_bw_reached


def test_drain_times_out_when_bdp_is_underestimated():
    """DRAIN must not trap the flow when the BDP estimate is too small."""
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05)
    cc.state = "DRAIN"
    cc._drain_rounds = 0
    cc.bdp = 1.0  # far below anything that can be in flight
    now = 0.1
    for _ in range(MAX_DRAIN_ROUNDS + 1):
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
    assert cc.state == "PROBE_BW"


def test_loss_cap_lifts_at_refill():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = run_until_probe_bw(cc, 0, 0.0)
    cc.bw_lo = cc.btl_bw * 0.8
    cc._update_bdp()
    assert cc.model_bw < cc.btl_bw
    for _ in range(10):
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
        if cc.probe_bw_phase == "REFILL":
            break
    assert cc.probe_bw_phase == "REFILL"
    assert cc.model_bw == cc.btl_bw


def test_trace_has_one_row_per_round():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn, now = 0, 0.0
    for _ in range(5):
        pn = run_round(cc, pn, now=now, rtt=0.05)
        now += 0.1
    assert [row["round"] for row in cc.trace] == list(range(cc.round_count))
    assert {"time", "round_s", "delivered_bytes", "lost_bytes", "state", "phase",
            "version", "cwnd", "btl_bw", "rtprop"} <= set(cc.trace[0])
    assert cc.trace[-1]["delivered_bytes"] > 0


def test_samples_shorter_than_rtprop_are_discarded():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    run_round(cc, 0, now=0.0, rtt=0.05)  # RTprop = 50 ms
    filter_before = list(cc.btl_bw_filter)
    # A burst acked 5 ms after sending would claim 2,000,000 bytes/s.
    sent = [FakePacket(10 + i, sent_time=1.0) for i in range(10)]
    for packet in sent:
        cc.on_packet_sent(packet=packet)
    for packet in sent:
        cc.on_packet_acked(now=1.005, packet=packet)
    new_samples = [bw for r, bw in cc.btl_bw_filter if (r, bw) not in filter_before]
    assert new_samples == []
