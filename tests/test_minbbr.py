"""Tests that MINBBR is actually the congestion controller aioquic uses."""
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.reno import RenoCongestionControl

from minquic.congestion import MinBbrCongestionControl
from minquic.connection import create_quic_configuration as minquic_configuration
from quic.connection import create_quic_configuration as quic_configuration


class FakePacket:
    def __init__(self, sent_bytes: int, sent_time: float = 0.0):
        self.sent_bytes = sent_bytes
        self.sent_time = sent_time


def test_minquic_connection_uses_minbbr():
    conn = QuicConnection(configuration=minquic_configuration(is_client=True))
    assert isinstance(conn._loss._cc, MinBbrCongestionControl)


def test_quic_baseline_uses_reno():
    conn = QuicConnection(configuration=quic_configuration(is_client=True))
    assert isinstance(conn._loss._cc, RenoCongestionControl)


def test_bytes_in_flight_accounting():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    packets = [FakePacket(1000) for _ in range(3)]
    for packet in packets:
        cc.on_packet_sent(packet=packet)
    assert cc.bytes_in_flight == 3000
    cc.on_packet_acked(now=1.0, packet=packets[0])
    cc.on_packets_expired(packets=[packets[1]])
    cc.on_packets_lost(now=1.0, packets=[packets[2]])
    assert cc.bytes_in_flight == 0


def test_rtt_measurement_updates_estimates():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    cc.on_rtt_measurement(now=1.0, rtt=0.05)
    assert cc.rtprop == 0.05
    assert cc.state == "PROBE_BW"
    # The window is computed before the state switch, so it lags one sample.
    assert cc.congestion_window == int(cc.bdp)
    cc.on_rtt_measurement(now=1.5, rtt=0.05)
    assert cc.congestion_window == int(cc.bdp * 2.0)
    # A delay spike well above RTprop switches to the BBRv2-compatible mode.
    cc.on_rtt_measurement(now=2.0, rtt=0.1)
    assert cc.state == "PROBE_RTT"
    cc.on_rtt_measurement(now=3.0, rtt=0.05)
    assert cc.state == "PROBE_BW"


def test_loss_reduces_bandwidth_and_keeps_minimum_window():
    cc = MinBbrCongestionControl(max_datagram_size=1200)
    cc.on_rtt_measurement(now=1.0, rtt=0.05)
    btl_bw = cc.btl_bw
    cc.btl_bw = 1.0  # force a tiny BDP after the loss cut
    cc.on_packets_lost(now=2.0, packets=[])
    assert cc.state == "DRAIN"
    assert cc.btl_bw < btl_bw
    assert cc.congestion_window >= 2 * 1200
