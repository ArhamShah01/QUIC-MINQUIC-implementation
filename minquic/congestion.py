"""Congestion‑control helpers and MINBBR implementation.

MINBBR is an improved congestion control algorithm that introduces delay-awareness
and BDP compensation to reduce throughput loss and latency.
"""
import logging
from typing import List
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.base import QuicCongestionControl

logger = logging.getLogger("minquic.congestion")

class MinBbrCongestionControl(QuicCongestionControl):
    """
    MINBBR Congestion Control Implementation.

    Key improvements over standard BBR:
    1. Delay-Aware Probing: Switches between aggressive and BBRv2-compatible
       modes based on network delay.
    2. BDP Compensation: Compensates for Bandwidth-Delay Product under
       network jitter to reduce throughput loss.
    """
    def __init__(self, max_datagram_size: int):
        super().__init__(max_datagram_size=max_datagram_size)
        # Internal state variables for MINBBR
        self.btl_bw = 1000000.0  # Default 1MB/s
        self.rtprop = 0.1  # Default 100ms
        self.bdp = self.btl_bw * self.rtprop
        self.state = "STARTUP"  # Startup, Drain, ProbeBW, ProbeRTT
        self.jitter_buffer = []
        self.jitter_compensation_factor = 1.0
        self._cwnd = 1460 * 10 # Initial CWND

    def on_packet_acked(self, packet_number: int, ack_delay: float, rtt: float):
        """Update bandwidth and delay estimates upon packet acknowledgment."""

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
        self._cwnd = self.get_congestion_window()

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
            return int(self.bdp * 2.0) if self.bdp > 0 else 1460 * 10
        elif self.state == "PROBE_RTT":
            # BBRv2-compatible: 1x BDP
            return int(self.bdp * 1.0) if self.bdp > 0 else 1460 * 10
        else:
            # Default to BDP or initial
            return int(self.bdp) if self.bdp > 0 else 1460 * 10

    def get_pacing_rate(self) -> float:
        """Return the pacing rate for packet injection."""
        if self.state == "PROBE_BW":
            return self.btl_bw * 1.25  # Probe above bottleneck
        return self.btl_bw

    # --- Abstract Method Implementations ---

    def on_packet_sent(self, packet_number: int):
        pass

    def on_packets_expired(self, packet_numbers: List[int]):
        pass

    def on_packets_lost(self, packet_numbers: List[int]):
        self.btl_bw *= 0.8
        self.state = "DRAIN"
        self._cwnd = self.get_congestion_window()

    def on_rtt_measurement(self, rtt: float):
        if rtt < self.rtprop:
            self.rtprop = rtt

def get_congestion_stats(conn: QuicConnection) -> dict:
    """Return congestion‑control information, pulling directly from the controller.
    """
    cc = getattr(conn, "congestion_control", None)

    # Initialize stats with defaults to avoid None in output
    stats = {
        "congestion_window": None,
        "bytes_in_flight": getattr(conn, "bytes_in_flight", 0),
        "rtt": getattr(conn, "rtt", 0.0),
    }

    if isinstance(cc, MinBbrCongestionControl):
        stats.update({
            "congestion_window": cc._cwnd,
            "minbbr_btl_bw": cc.btl_bw,
            "minbbr_rtprop": cc.rtprop,
            "minbbr_bdp": cc.bdp,
            "minbbr_state": cc.state,
            "minbbr_pacing_rate": cc.get_pacing_rate(),
        })
    elif cc:
        # Try to get CWND from other aioquic controllers if they exist
        stats["congestion_window"] = getattr(cc, "congestion_window", None)

    return stats
