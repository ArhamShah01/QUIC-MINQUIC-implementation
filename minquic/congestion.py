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

# BtlBW is the max delivery rate over this many round trips (as in BBR).
BTLBW_FILTER_ROUNDS = 10
# Algorithm 1: a round whose min RTT exceeds K_TARGET_RTT * RTprop is treated
# as jitter-inflated, and the oldest BtlBW sample is discarded.
# The paper does not give a value for k; tune it here.
K_TARGET_RTT = 1.25


class MinBbrCongestionControl(QuicCongestionControl):
    """
    MINBBR Congestion Control Implementation.

    Key improvements over standard BBR:
    1. Delay-Aware Probing: Switches between aggressive and BBRv2-compatible
       modes based on network delay.
    2. BDP Compensation: Compensates for Bandwidth-Delay Product under
       network jitter to reduce throughput loss (the "MIN BtlBW filter",
       Algorithm 1 of the MINQUIC paper).

    aioquic reads ``congestion_window`` and ``bytes_in_flight`` from this object
    to decide how much it may send, so both must be kept up to date here.
    """
    def __init__(self, *, max_datagram_size: int) -> None:
        super().__init__(max_datagram_size=max_datagram_size)
        self._min_window = K_MINIMUM_WINDOW * max_datagram_size
        # Internal state variables for MINBBR
        self.btl_bw = 0.0  # bytes/s, max of btl_bw_filter
        self.rtprop = None  # seconds, min RTT seen; None until the first sample
        self.bdp = 0.0
        self.state = "STARTUP"  # Startup, Drain, ProbeBW, ProbeRTT
        self.congestion_window = 1460 * 10  # Initial CWND

        # Delivery-rate sampling: bytes delivered so far, when the latest ACK
        # arrived, and per in-flight packet the values at the time it was sent.
        self._delivered = 0
        self._delivered_time = None
        self._packet_state = {}  # (epoch, packet_number) -> (delivered, delivered_time)

        # Round trips: a round ends when a packet sent after the previous
        # round ended is acknowledged.
        self.round_count = 0
        self._next_round_delivered = 0
        self._round_min_rtt = None

        # BtlBW max filter: one (round, max delivery rate in that round) entry
        # per round, covering the last BTLBW_FILTER_ROUNDS rounds.
        self.btl_bw_filter = []

    def _on_bandwidth_sample(self, bw: float) -> None:
        """Add a delivery-rate sample to the current round's filter entry."""
        if self.btl_bw_filter and self.btl_bw_filter[-1][0] == self.round_count:
            if bw > self.btl_bw_filter[-1][1]:
                self.btl_bw_filter[-1] = (self.round_count, bw)
        else:
            self.btl_bw_filter.append((self.round_count, bw))
        self._update_btl_bw()

    def _update_btl_bw(self) -> None:
        oldest_round = self.round_count - BTLBW_FILTER_ROUNDS + 1
        self.btl_bw_filter = [e for e in self.btl_bw_filter if e[0] >= oldest_round]
        self.btl_bw = max((bw for _, bw in self.btl_bw_filter), default=0.0)

    def _on_round_end(self) -> None:
        """Apply the MIN BtlBW filter (Algorithm 1) to the round that just ended."""
        if self.rtprop is not None and self._round_min_rtt is not None:
            target_rtt = K_TARGET_RTT * self.rtprop
            should_min = self._round_min_rtt > target_rtt
            # Keep at least one sample so BtlBW never collapses to zero.
            if should_min and len(self.btl_bw_filter) > 1:
                del self.btl_bw_filter[0]
        self._round_min_rtt = None
        self.round_count += 1
        self._update_btl_bw()

    def _update_estimates(self, rtt: float) -> None:
        """Update delay estimates, BDP and state from an RTT sample."""

        # Update RTprop (min RTT)
        if self.rtprop is None or rtt < self.rtprop:
            self.rtprop = rtt
        if self._round_min_rtt is None or rtt < self._round_min_rtt:
            self._round_min_rtt = rtt

        # BtlBW comes from measured delivery rate (see on_packet_acked); the
        # MIN BtlBW filter already dropped jitter-inflated samples.
        self.bdp = self.btl_bw * self.rtprop

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
        # RTT-based estimates are updated in on_rtt_measurement, which aioquic
        # calls right after the acked packets are processed.
        self.bytes_in_flight -= packet.sent_bytes
        self._delivered += packet.sent_bytes
        self._delivered_time = now

        state = self._packet_state.pop((packet.epoch, packet.packet_number), None)
        if state is None:
            return
        delivered_at_send, delivered_time_at_send = state

        # Delivery rate: bytes acknowledged since this packet was sent, over
        # the time between the ACK before it was sent and this ACK.
        if delivered_time_at_send is not None:
            interval = now - delivered_time_at_send
            if interval > 0:
                self._on_bandwidth_sample((self._delivered - delivered_at_send) / interval)

        if delivered_at_send >= self._next_round_delivered:
            self._next_round_delivered = self._delivered
            self._on_round_end()

    def on_packet_sent(self, *, packet: QuicSentPacket) -> None:
        self.bytes_in_flight += packet.sent_bytes
        if self._delivered_time is None:
            # Nothing acked yet: measure the first samples from the send time.
            self._delivered_time = packet.sent_time
        self._packet_state[(packet.epoch, packet.packet_number)] = (
            self._delivered,
            self._delivered_time,
        )

    def on_packets_expired(self, *, packets: Iterable[QuicSentPacket]) -> None:
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes
            self._packet_state.pop((packet.epoch, packet.packet_number), None)

    def on_packets_lost(self, *, now: float, packets: Iterable[QuicSentPacket]) -> None:
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes
            self._packet_state.pop((packet.epoch, packet.packet_number), None)
        # Cut the filter samples too, or the next update would undo the cut.
        self.btl_bw_filter = [(r, bw * 0.8) for r, bw in self.btl_bw_filter]
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
