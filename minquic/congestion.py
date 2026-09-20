"""Congestion‑control helpers and MINBBR implementation.

MINBBR is an improved congestion control algorithm that introduces delay-awareness
and BDP compensation to reduce throughput loss and latency.

The algorithm is registered with aioquic under the name ``"minbbr"``; select it
by setting ``QuicConfiguration.congestion_control_algorithm = "minbbr"``.
"""
import logging
import math
from typing import Iterable
from aioquic.quic.connection import QuicConnection
from aioquic.quic.congestion.base import (
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

# Algorithm 2 (dual-mode ProbeBW) sensitivity, values from the paper.
PHI_R1 = 1.1    # MinRTT above PHI_R1 * RTprop suggests a loss-based competitor
PHI_R2 = 1.05   # MinRTT at or below PHI_R2 * RTprop suggests it has gone
THETA_R1 = 2    # consecutive rounds before switching to BBRv2 mode
THETA_R2 = 4    # consecutive rounds before switching back to MINBBR mode

# STARTUP ends once BtlBW grows by less than this factor for this many rounds.
FULL_BW_THRESHOLD = 1.25
FULL_BW_ROUNDS = 3

# PROBE_RTT: re-measure RTprop if it has not been refreshed for this long.
RTPROP_EXPIRY = 10.0  # seconds
PROBE_RTT_DURATION = 0.2  # seconds

# ProbeBW cycles through BBRv2's sub-states, one round each except CRUISE.
# Only the congestion window can be steered (aioquic paces at cwnd / srtt),
# so each sub-state sets a cwnd gain relative to BDP. DOWN drains the queue
# this flow built in UP, so MinRTT measured in CRUISE reflects other traffic.
PROBE_BW_PHASES = ("DOWN", "CRUISE", "REFILL", "UP")
CRUISE_ROUNDS = 6
# The paper gives no cwnd gains; these are implementation choices. UP uses
# BBR's 1.25 probing gain: with the window as the only control, larger gains
# overflow the bottleneck queue every cycle. CRUISE keeps a little above one
# BDP in flight so ACK timing does not idle the link, while staying below
# Algorithm 2's PHI_R1 threshold so the flow's own queue is not mistaken for
# a competitor.
PROBE_BW_CWND_GAINS = {
    # Aggressive probing when no loss-based competitor is detected.
    "MINBBR": {"DOWN": 0.75, "CRUISE": 1.1, "REFILL": 1.0, "UP": 1.25},
    # BBRv2-compatible: gentler probing and headroom in CRUISE, which leaves
    # queue space for loss-based flows.
    "BBRV2": {"DOWN": 0.75, "CRUISE": 0.85, "REFILL": 1.0, "UP": 1.25},
}
DRAIN_CWND_GAIN = 1.0

# Loss response (implementation choice, BBRv2-style): at the end of a round
# whose loss rate exceeded LOSS_RATE_THRESHOLD, cap the model bandwidth at
# LOSS_BW_FACTOR of its current value. The cap is short-term and is lifted
# when ProbeBW next enters REFILL. The threshold matters under jitter, where
# late packets are declared lost although nothing was dropped; reacting to
# every such packet collapses the estimate.
LOSS_BW_FACTOR = 0.8
LOSS_RATE_THRESHOLD = 0.02

# DRAIN ends when the queue this flow built has left the network. Give up
# after this many rounds anyway: if BtlBW was underestimated, bytes in flight
# may never fall below the (too small) BDP.
MAX_DRAIN_ROUNDS = 2

INITIAL_WINDOW_PACKETS = 10
MIN_WINDOW_PACKETS = 4


class MinBbrCongestionControl(QuicCongestionControl):
    """
    MINBBR Congestion Control Implementation.

    Key improvements over standard BBR:
    1. Delay-Aware Probing: ProbeBW runs in MINBBR (aggressive) or BBRv2
       (competitor-friendly) mode, chosen per round from MinRTT vs RTprop
       (Algorithm 2 of the MINQUIC paper).
    2. BDP Compensation: Compensates for Bandwidth-Delay Product under
       network jitter to reduce throughput loss (the "MIN BtlBW filter",
       Algorithm 1 of the MINQUIC paper).

    aioquic reads ``congestion_window`` and ``bytes_in_flight`` from this object
    to decide how much it may send, so both must be kept up to date here.
    """
    def __init__(self, *, max_datagram_size: int) -> None:
        super().__init__(max_datagram_size=max_datagram_size)
        self._max_datagram_size = max_datagram_size
        self._initial_window = INITIAL_WINDOW_PACKETS * max_datagram_size
        self._min_window = MIN_WINDOW_PACKETS * max_datagram_size
        self.congestion_window = self._initial_window

        # Path model
        self.btl_bw = 0.0  # bytes/s, max of btl_bw_filter
        self.bw_lo = math.inf  # bytes/s, short-term cap after loss
        self.rtprop = None  # seconds, min RTT seen; None until the first sample
        self._rtprop_stamp = 0.0
        self._rtprop_expired = False
        self.bdp = 0.0

        # State machine: STARTUP, DRAIN, PROBE_BW, PROBE_RTT
        self.state = "STARTUP"
        self.probe_bw_version = "MINBBR"  # or "BBRV2"
        self._full_bw = 0.0
        self._full_bw_count = 0
        self._full_bw_reached = False
        self._min_buffer = 0  # Algorithm 2: rounds with MinRTT above threshold
        self._buffer_empty = 0  # Algorithm 2: rounds with MinRTT near RTprop
        self._probe_rtt_done_stamp = None
        self.probe_bw_phase = None  # PROBE_BW sub-state, see PROBE_BW_PHASES
        self._phase_rounds = 0
        self._cruise_min_rtt = None
        self._round_lost_bytes = 0
        self._round_start_delivered = 0
        self._drain_rounds = 0
        self._last_round_time = None

        # Delivery-rate sampling (as in BBR): bytes delivered so far, when the
        # latest ACK arrived, the send time of the latest acked packet, and
        # per in-flight packet the values at the time it was sent.
        self._delivered = 0
        self._delivered_time = None
        self._first_sent_time = None
        # (epoch, packet_number) -> (delivered, delivered_time, first_sent_time)
        self._packet_state = {}

        # Round trips: a round ends when a packet sent after the previous
        # round ended is acknowledged.
        self.round_count = 0
        self._next_round_delivered = 0
        self._round_min_rtt = None

        # BtlBW max filter: one (round, max delivery rate in that round) entry
        # per round, covering the last BTLBW_FILTER_ROUNDS rounds.
        self.btl_bw_filter = []

        # One row per round trip, for plotting MINBBR's behaviour over time.
        self.trace = []

    # --- Path model ---

    @property
    def model_bw(self) -> float:
        """Bandwidth used for BDP: BtlBW, capped by bw_lo after loss."""
        return min(self.btl_bw, self.bw_lo)

    def _update_bdp(self) -> None:
        if self.rtprop is not None:
            self.bdp = self.model_bw * self.rtprop

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
        self._update_bdp()

    def _apply_min_btlbw_filter(self) -> None:
        """Algorithm 1: discard the oldest BtlBW sample after a jittery round."""
        target_rtt = K_TARGET_RTT * self.rtprop
        should_min = self._round_min_rtt > target_rtt
        # Keep at least one sample so BtlBW never collapses to zero.
        if should_min and len(self.btl_bw_filter) > 1:
            del self.btl_bw_filter[0]

    # --- State machine ---

    def _check_full_bw(self) -> None:
        """STARTUP ends when BtlBW stops growing for FULL_BW_ROUNDS rounds."""
        if self.btl_bw >= self._full_bw * FULL_BW_THRESHOLD:
            self._full_bw = self.btl_bw
            self._full_bw_count = 0
            return
        self._full_bw_count += 1
        if self._full_bw_count >= FULL_BW_ROUNDS:
            self._full_bw_reached = True

    def _restart_startup(self) -> None:
        self.state = "STARTUP"
        self.probe_bw_phase = None
        self._full_bw = 0.0
        self._full_bw_count = 0
        self._full_bw_reached = False

    def _update_probe_bw_version(self, min_rtt: float) -> None:
        """Algorithm 2: pick MINBBR or BBRv2 ProbeBW from a ProbeCruise MinRTT."""
        if self.probe_bw_version == "MINBBR":
            threshold = PHI_R1 * self.rtprop
            if min_rtt > threshold:
                self._min_buffer += 1
            else:
                self._min_buffer = 0
            if self._min_buffer >= THETA_R1:
                # A loss-based competitor is likely filling the queue: yield
                # like BBRv2, and restart from STARTUP to regain bandwidth.
                self.probe_bw_version = "BBRV2"
                self._min_buffer = 0
                self._restart_startup()
        else:
            switch_thld = PHI_R2 * self.rtprop
            if min_rtt <= switch_thld:
                self._buffer_empty += 1
            else:
                self._buffer_empty = 0
            if self._buffer_empty >= THETA_R2:
                self.probe_bw_version = "MINBBR"
                self._buffer_empty = 0

    def _enter_probe_bw(self) -> None:
        self.state = "PROBE_BW"
        self._drain_rounds = 0
        self.probe_bw_phase = "DOWN"
        self._phase_rounds = 0
        self._cruise_min_rtt = None

    def _advance_probe_bw_phase(self) -> None:
        """Move through the ProbeBW sub-states at the end of each round."""
        self._phase_rounds += 1
        if self.probe_bw_phase == "CRUISE":
            if self._round_min_rtt is not None and (
                self._cruise_min_rtt is None or self._round_min_rtt < self._cruise_min_rtt
            ):
                self._cruise_min_rtt = self._round_min_rtt
            if self._phase_rounds < CRUISE_ROUNDS:
                return
            # ProbeCruise ended: run Algorithm 2 on its MinRTT.
            if self._cruise_min_rtt is not None:
                self._update_probe_bw_version(self._cruise_min_rtt)
            self._cruise_min_rtt = None
            if self.state != "PROBE_BW":
                return  # Algorithm 2 restarted STARTUP
        index = PROBE_BW_PHASES.index(self.probe_bw_phase)
        self.probe_bw_phase = PROBE_BW_PHASES[(index + 1) % len(PROBE_BW_PHASES)]
        self._phase_rounds = 0
        if self.probe_bw_phase == "REFILL":
            # Start of a new probing cycle: lift the short-term loss cap.
            self.bw_lo = math.inf
            self._update_bdp()

    def _apply_loss_response(self) -> None:
        """Cap the model bandwidth if this round lost more than the threshold."""
        delivered = self._delivered - self._round_start_delivered
        total = delivered + self._round_lost_bytes
        loss_rate = self._round_lost_bytes / total if total else 0.0
        self._round_lost_bytes = 0
        self._round_start_delivered = self._delivered
        if loss_rate <= LOSS_RATE_THRESHOLD:
            return
        self.bw_lo = LOSS_BW_FACTOR * self.model_bw
        self._update_bdp()
        if self.state == "STARTUP":
            # Real loss means the pipe is full: stop growing and drain.
            self._full_bw_reached = True
            self.state = "DRAIN"
            self._drain_rounds = 0

    def _on_round_end(self, now: float) -> None:
        self.trace.append({
            "time": now,
            # Round duration: much longer than the RTT means the sender stalled
            # (for example waiting out a probe timeout).
            "round_s": None if self._last_round_time is None else round(now - self._last_round_time, 4),
            "delivered_bytes": self._delivered - self._round_start_delivered,
            "lost_bytes": self._round_lost_bytes,
            "round": self.round_count,
            "state": self.state,
            "phase": self.probe_bw_phase,
            "version": self.probe_bw_version,
            "cwnd": self.congestion_window,
            "bytes_in_flight": self.bytes_in_flight,
            "btl_bw": self.btl_bw,
            "bw_lo": None if math.isinf(self.bw_lo) else self.bw_lo,
            "rtprop": self.rtprop,
            "round_min_rtt": self._round_min_rtt,
        })
        self._last_round_time = now
        self._apply_loss_response()
        if self.state == "DRAIN":
            self._drain_rounds += 1
        if self.rtprop is not None and self._round_min_rtt is not None:
            self._apply_min_btlbw_filter()
        if self.state == "PROBE_BW":
            self._advance_probe_bw_phase()
        self._round_min_rtt = None
        self.round_count += 1
        self._update_btl_bw()

        if self.state == "STARTUP":
            self._check_full_bw()
            if self._full_bw_reached:
                self.state = "DRAIN"

    def _update_state(self, now: float) -> None:
        if self.state == "DRAIN" and (
            self.bytes_in_flight <= self.bdp or self._drain_rounds >= MAX_DRAIN_ROUNDS
        ):
            self._enter_probe_bw()

        # Enter PROBE_RTT when RTprop has not been refreshed recently.
        if self._rtprop_expired and self.state != "PROBE_RTT":
            self.state = "PROBE_RTT"
            self.probe_bw_phase = None
            self._probe_rtt_done_stamp = None
        self._rtprop_expired = False

        if self.state == "PROBE_RTT":
            if self._probe_rtt_done_stamp is None:
                if self.bytes_in_flight <= self._min_window:
                    self._probe_rtt_done_stamp = now + PROBE_RTT_DURATION
            elif now >= self._probe_rtt_done_stamp:
                self._rtprop_stamp = now
                if self._full_bw_reached:
                    self._enter_probe_bw()
                else:
                    self._restart_startup()

    def _update_congestion_window(self, acked_bytes: int) -> None:
        if self.state == "PROBE_RTT":
            self.congestion_window = self._min_window
            return
        if self.state == "STARTUP":
            # Grow by every acked byte (doubling per round) until full BW.
            cwnd = self.congestion_window + acked_bytes
        else:
            cwnd = min(self.congestion_window + acked_bytes, self.get_congestion_window())
        self.congestion_window = max(cwnd, self._min_window)

    def get_congestion_window(self) -> int:
        """Return the target congestion window for the current state."""
        if self.bdp <= 0:
            return self._initial_window
        if self.state == "PROBE_BW":
            gain = PROBE_BW_CWND_GAINS[self.probe_bw_version][self.probe_bw_phase]
        else:
            gain = DRAIN_CWND_GAIN
        # Never drop below the minimum window, or the connection stalls.
        return max(int(self.bdp * gain), self._min_window)

    def get_pacing_rate(self) -> float:
        """Return the pacing rate for packet injection.

        Reported in metrics only: aioquic derives its own pacing rate from
        ``congestion_window`` and the smoothed RTT.
        """
        if self.state == "PROBE_BW" and self.probe_bw_phase == "UP":
            return self.model_bw * 1.25  # Probe above bottleneck
        if self.state == "PROBE_BW" and self.probe_bw_phase == "DOWN":
            return self.model_bw * 0.75  # Drain the queue built while probing
        return self.model_bw

    # --- aioquic QuicCongestionControl interface ---

    def on_packet_acked(self, *, now: float, packet: QuicSentPacket) -> None:
        self.bytes_in_flight -= packet.sent_bytes
        self._delivered += packet.sent_bytes
        self._delivered_time = now

        state = self._packet_state.pop((packet.epoch, packet.packet_number), None)
        if state is not None:
            delivered_at_send, delivered_time_at_send, first_sent_at_send = state

            # Delivery rate: bytes acknowledged since this packet was sent,
            # over the longer of the send and ACK intervals, so bunched ACKs
            # cannot inflate the estimate. Samples shorter than RTprop are
            # also distorted by ACK bunching and are discarded.
            send_elapsed = packet.sent_time - first_sent_at_send
            ack_elapsed = now - delivered_time_at_send
            interval = max(send_elapsed, ack_elapsed)
            self._first_sent_time = packet.sent_time
            if interval > 0 and (self.rtprop is None or interval >= self.rtprop):
                self._on_bandwidth_sample(
                    (self._delivered - delivered_at_send) / interval
                )

            if delivered_at_send >= self._next_round_delivered:
                self._next_round_delivered = self._delivered
                self._on_round_end(now)

        self._update_state(now)
        self._update_congestion_window(packet.sent_bytes)

    def on_packet_sent(self, *, packet: QuicSentPacket) -> None:
        if self.bytes_in_flight == 0:
            # Nothing in flight (start or after idle): measure from now.
            self._delivered_time = packet.sent_time
            self._first_sent_time = packet.sent_time
        self.bytes_in_flight += packet.sent_bytes
        self._packet_state[(packet.epoch, packet.packet_number)] = (
            self._delivered,
            self._delivered_time,
            self._first_sent_time,
        )

    def on_packets_expired(self, *, packets: Iterable[QuicSentPacket]) -> None:
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes
            self._packet_state.pop((packet.epoch, packet.packet_number), None)

    def on_packets_lost(self, *, now: float, packets: Iterable[QuicSentPacket]) -> None:
        # Losses are accumulated and answered once per round, in
        # _apply_loss_response, so that a round's loss rate can be measured.
        for packet in packets:
            self.bytes_in_flight -= packet.sent_bytes
            self._round_lost_bytes += packet.sent_bytes
            self._packet_state.pop((packet.epoch, packet.packet_number), None)

    def on_rtt_measurement(self, *, now: float, rtt: float) -> None:
        # Update RTprop (min RTT), or take a fresh sample once it has expired;
        # the expiry also triggers PROBE_RTT on the next ACK.
        self._rtprop_expired = (
            self.rtprop is not None and now - self._rtprop_stamp > RTPROP_EXPIRY
        )
        if self.rtprop is None or rtt <= self.rtprop or self._rtprop_expired:
            self.rtprop = rtt
            self._rtprop_stamp = now
        if self._round_min_rtt is None or rtt < self._round_min_rtt:
            self._round_min_rtt = rtt
        self._update_bdp()

    def get_log_data(self) -> dict:
        data = super().get_log_data()
        data["minbbr_state"] = self.state
        data["minbbr_probe_bw_version"] = self.probe_bw_version
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
            "minbbr_bw_lo": None if math.isinf(cc.bw_lo) else cc.bw_lo,
            "minbbr_rtprop": cc.rtprop,
            "minbbr_bdp": cc.bdp,
            "minbbr_state": cc.state,
            "minbbr_probe_bw_version": cc.probe_bw_version,
            "minbbr_probe_bw_phase": cc.probe_bw_phase,
            "minbbr_pacing_rate": cc.get_pacing_rate(),
        })

    return stats
