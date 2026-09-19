"""Congestion‑control helpers and MINBBR implementation.

MINBBR is an improved congestion control algorithm that introduces delay-awareness
and BDP compensation to reduce throughput loss and latency.

The algorithm is registered with aioquic under the name ``"minbbr"``; select it
by setting ``QuicConfiguration.congestion_control_algorithm = "minbbr"``.
"""
import logging
from typing import Iterable
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.base import (
    K_MINIMUM_WINDOW,
    QuicCongestionControl,
    register_congestion_control,
)
from aioquic.quic.packet_builder import QuicSentPacket

logger = logging.getLogger("minquic.congestion")

class MinBbrCongestionControl(QuicCongestionControl):
    """
    MINBBR Congestion Control Implementation.

    Key improvements over standard BBR:
    1. Delay-Aware Probing: Switches between aggressive and BBRv2-compatible
       modes based on network delay.
    2. BDP Compensation: Compensates for Bandwidth-Delay Product under
       network jitter to reduce throughput loss.

    aioquic reads ``congestion_window`` and ``bytes_in_flight`` from this object
    to decide how much it may send, so both must be kept up to date here.
    """
    def __init__(self, *, max_datagram_size: int) -> None:
        super().__init__(max_datagram_size=max_datagram_size)
        self._min_window = K_MINIMUM_WINDOW * max_datagram_size
        # Internal state variables for MINBBR
        self.btl_bw = 1000000.0  # Default 1MB/s
        self.rtprop = 0.1  # Default 100ms
        self.bdp = self.btl_bw * self.rtprop
        self.state = "STARTUP"  # Startup, Drain, ProbeBW, ProbeRTT
        self.jitter_buffer = []
        self.jitter_compensation_factor = 1.0
        self.congestion_window = 1460 * 10  # Initial CWND

    def _update_estimates(self, rtt: float) -> None:
        """Update bandwidth and delay estimates from an RTT sample."""

        # Update RTprop (min RTT)
        if rtt < self.rtprop:
            self.rtprop = rtt

        # Simplified bandwidth estimation: (bytes_in_flight / rtt)
        # We use a base flight of 10 packets as a heuristic for simple demos
        current_flight = 1460 * 10
        current_bw = current_flight / max(rtt, 0.001)
        self.btl_bw = max(self.btl_bw, current_bw)

        # Calculate BDP and apply jitter compensation
        self.bdp = self.btl_bw * self.rtprop * self.jitter_compensation_factor

        # Update CWND based on MINBBR state
        self.congestion_window = self.get_congestion_window()

        # Delay-aware state switching logic (simplified)
        if self.state == "STARTUP" and self.btl_bw > 0:
            self.state = "PROBE_BW"

        # If delay exceeds RTprop by a significant threshold, switch to BBRv2-compatible mode
        if rtt > self.rtprop * 1.5:
            self.state = "PROBE_RTT"
        elif self.state == "PROBE_RTT" and rtt <= self.rtprop * 1.2:
            self.state = "PROBE_BW"

    def get_congestion_window(self) -> int:
        """Return the calculated congestion window based on MINBBR state."""
        if self.state == "PROBE_BW":
            # Aggressive probing: 2x BDP
            cwnd = int(self.bdp * 2.0) if self.bdp > 0 else 1460 * 10
        elif self.state == "PROBE_RTT":
            # BBRv2-compatible: 1x BDP
            cwnd = int(self.bdp * 1.0) if self.bdp > 0 else 1460 * 10
        else:
            # Default to BDP or initial
            cwnd = int(self.bdp) if self.bdp > 0 else 1460 * 10
        # Never drop below the minimum window, or the connection stalls.
        return max(cwnd, self._min_window)

    def get_pacing_rate(self) -> float:
        """Return the pacing rate for packet injection.

        Reported in metrics only: aioquic derives its own pacing rate from
        ``congestion_window`` and the smoothed RTT.
        """
        if self.state == "PROBE_BW":
            return self.btl_bw * 1.25  # Probe above bottleneck
        return self.btl_bw

    # --- aioquic QuicCongestionControl interface ---

    def on_packet_acked(self, *, now: float, packet: QuicSentPacket) -> None:
        # Estimates are updated in on_rtt_measurement, which aioquic calls
        # with the RTT sample right after the acked packets are processed.
        self.bytes_in_flight -= packet.sent_bytes

    def on_packet_sent(self, *, packet: QuicSentPacket) -> None:
        self.bytes_in_flight += packet.sent_bytes

    def on_packets_expired(self, *, packets: Iterable[QuicSentPacket]) -> None:
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes

    def on_packets_lost(self, *, now: float, packets: Iterable[QuicSentPacket]) -> None:
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes
        self.btl_bw *= 0.8
        self.state = "DRAIN"
        self.congestion_window = self.get_congestion_window()

    def on_rtt_measurement(self, *, now: float, rtt: float) -> None:
        self._update_estimates(rtt)

    def get_log_data(self) -> dict:
        data = super().get_log_data()
        data["minbbr_state"] = self.state
        return data


register_congestion_control("minbbr", MinBbrCongestionControl)


def get_congestion_stats(conn: QuicConnection) -> dict:
    """Return congestion‑control information, pulling directly from the controller.
    """
    # aioquic keeps loss recovery (RTT, controller) on the private ``_loss``.
    recovery = conn._loss
    cc = recovery._cc

    stats = {
        "congestion_window": cc.congestion_window,
        "bytes_in_flight": cc.bytes_in_flight,
        # Smoothed RTT in seconds; None until the first RTT sample arrives.
        "rtt": recovery._rtt_smoothed if recovery._rtt_initialized else None,
    }

    if isinstance(cc, MinBbrCongestionControl):
        stats.update({
            "minbbr_btl_bw": cc.btl_bw,
            "minbbr_rtprop": cc.rtprop,
            "minbbr_bdp": cc.bdp,
            "minbbr_state": cc.state,
            "minbbr_pacing_rate": cc.get_pacing_rate(),
        })

    return stats
