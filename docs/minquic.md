# MINQUIC Implementation

MINQUIC reuses the QUIC baseline and changes one component: congestion
control. ``minquic/congestion.py`` implements **MINBBR** (Sun, *Research on an
Improved QUIC Protocol: MINQUIC*, BDICN 2023), registers it with aioquic as
``"minbbr"``, and ``minquic/connection.py`` selects it through
``QuicConfiguration.congestion_control_algorithm``. Everything else (echo
server, client, metrics) mirrors the ``quic`` package, so both protocols can be
compared under identical conditions (see ``docs/experiments.md``).

aioquic lets a congestion controller set only the congestion window; it paces
at ``cwnd / smoothed RTT`` itself. MINBBR therefore steers sending through the
window, using a gain relative to the estimated BDP in each state.

## Path model

- **BtlBW**: measured delivery rate, maximum over the last 10 round trips, as
  in BBR. Each ACK gives a sample: bytes acknowledged since the packet was
  sent, divided by the longer of the send interval and the ACK interval.
  Samples over an interval shorter than RTprop are discarded, since bunched
  ACKs would otherwise inflate them.
- **RTprop**: minimum RTT, refreshed through PROBE_RTT when it has not been
  seen for 10 s.
- **BDP** = min(BtlBW, bw_lo) × RTprop, where ``bw_lo`` is the short-term cap
  after loss (below).

## State machine

| State | Behaviour | Exit |
| ----- | --------- | ---- |
| STARTUP | Window grows by every acknowledged byte (doubles per round), capped at 3 × BDP | BtlBW grows < 25 % for 3 rounds, or a round with > 2 % loss |
| DRAIN | Window 1 × BDP | Bytes in flight ≤ BDP, or 2 rounds |
| PROBE_BW | Cycles DOWN → CRUISE (6 rounds) → REFILL → UP, one round each otherwise | RTprop expiry → PROBE_RTT |
| PROBE_RTT | Window 4 packets for 200 ms | Back to PROBE_BW (or STARTUP) |

PROBE_BW runs in one of two modes, chosen by Algorithm 2:

| Phase | MINBBR mode gain | BBRv2 mode gain |
| ----- | ---------------- | --------------- |
| DOWN | 0.75 | 0.75 |
| CRUISE | 1.1 | 0.85 |
| REFILL | 1.0 | 1.0 |
| UP | 1.25 | 1.25 |

With only the window to steer by, the two modes differ in CRUISE: MINBBR mode
keeps a little more than one BDP in flight, BBRv2 mode leaves headroom for
loss-based flows. UP at 1.25 matches BBR's probing gain; a window of 2 × BDP
overflowed the bottleneck queue on every cycle.

## What comes from the paper and what is an implementation choice

| Element | Source |
| ------- | ------ |
| Algorithm 1, MIN BtlBW filter: after a round whose MinRTT > k × RTprop, discard the oldest BtlBW sample | Paper |
| k = 1.25 | **Implementation choice** (the paper gives no value) |
| Algorithm 2, dual-mode ProbeBW: switch to BBRv2 mode (and restart STARTUP) after θr1 ProbeCruise phases with MinRTT > φr1 × RTprop; return to MINBBR mode after θr2 phases with MinRTT ≤ φr2 × RTprop | Paper |
| φr1 = 1.1, φr2 = 1.05, θr1 = 2, θr2 = 4 | Paper |
| STARTUP exit after 3 rounds on a BtlBW plateau | Paper (BBR background), 25 % growth threshold from BBR |
| ProbeBW sub-states DOWN / CRUISE / REFILL / UP | BBRv2, as referenced by the paper |
| Window gains per phase and mode (table above) | **Implementation choice** (the paper gives none) |
| Loss response: at the end of a round whose loss rate exceeded 2 %, ``bw_lo`` = 0.8 × current model bandwidth; lifted at the next REFILL; such a round also ends STARTUP | **Implementation choice**, modelled on BBRv2's ``bw_lo`` and loss threshold |
| DRAIN ends after 2 rounds even if bytes in flight still exceed the BDP | **Implementation choice** (prevents a stall when BtlBW is underestimated) |
| STARTUP window capped at 3 × BDP | **Implementation choice**; uncapped doubling overshot a 1.5 MB bottleneck queue by megabytes on a fast path, and the resulting loss and queueing stalled the connection |
| 10-round BtlBW window, 10 s RTprop expiry, 200 ms PROBE_RTT, 4-packet minimum window | BBR defaults |

All tunable values are constants at the top of ``minquic/congestion.py``.

## Inspecting MINBBR

- ``python -m minquic.client ... --trace`` writes one row per round trip:
  state, phase, mode, window, bytes in flight, BtlBW, bw_lo, RTprop and the
  round's minimum RTT.
- The client's metrics include the final ``minbbr_*`` values.
- ``tests/test_minbbr.py`` covers each mechanism with synthetic packets.

## Known limitations

- Pacing cannot be set directly, so the pacing gains of BBR are approximated
  through window gains.
- Under jitter, RTprop settles at the jitter minimum, so Algorithm 2 with the
  paper's φr1 = 1.1 can detect a competitor where there is none and switch to
  BBRv2 mode.
- Jitter also makes QUIC's loss detection declare late packets lost. The 2 %
  loss-rate threshold keeps those spurious losses from collapsing the
  bandwidth estimate, but they still cost throughput.
- On plain loopback (no netem) RTprop is far below the RTT under load
  (processing delay dominates), so MINBBR keeps a small window; compare the
  protocols only under netem conditions.
