"""Tests that MINBBR is actually the congestion controller aioquic uses."""
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.reno import RenoCongestionControl

from minquic.congestion import MinBbrCongestionControl
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


def test_btl_bw_is_measured_delivery_rate():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    # 10 x 1000 bytes delivered in 50 ms -> 200,000 bytes/s.
    run_round(cc, 0, now=0.0, rtt=0.05)
    assert cc.btl_bw == 10_000 / 0.05
    assert cc.rtprop == 0.05
    assert cc.bdp == cc.btl_bw * cc.rtprop
    assert cc.state == "PROBE_BW"


def test_state_switching_on_delay():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    pn = run_round(cc, 0, now=0.0, rtt=0.05)
    pn = run_round(cc, pn, now=0.1, rtt=0.05)
    assert cc.state == "PROBE_BW"
    assert cc.congestion_window == int(cc.bdp * 2.0)
    # A delay spike well above RTprop switches to the BBRv2-compatible mode.
    pn = run_round(cc, pn, now=0.2, rtt=0.1)
    assert cc.state == "PROBE_RTT"
    run_round(cc, pn, now=0.4, rtt=0.05)
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


def test_loss_reduces_bandwidth_and_keeps_minimum_window():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    run_round(cc, 0, now=0.0, rtt=0.05)
    btl_bw = cc.btl_bw
    cc.on_packets_lost(now=1.0, packets=[])
    assert cc.state == "DRAIN"
    assert cc.btl_bw == btl_bw * 0.8
    assert cc.congestion_window >= 2 * 1200
