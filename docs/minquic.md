# MINQUIC Extension Plan

*To be completed after the QUIC baseline is verified.*

The MINQUIC phase will build directly on the existing ``quic`` package. The
approach is to keep the overall architecture unchanged and replace only the
components identified in the research paper (e.g., congestion control, packet
header format, loss detection tweaks). By mirroring the directory structure
under ``minquic/`` we can run side‑by‑side experiments and generate direct
comparisons of the metric CSV files produced by the baseline and the
enhanced protocol.

Key steps (planned):
1. Create ``minquic/`` package mirroring ``quic/``.
2. Copy existing modules and modify the ones highlighted by the MINQUIC
   research (e.g., ``congestion.py`` to implement the proposed algorithm).
3. Adjust ``client.py`` and ``server.py`` to import from ``minquic`` when the
   MINQUIC mode is selected via a command‑line flag or configuration option.
4. Re‑run the experiment suite, storing results under
   ``experiments/results/minquic_\<timestamp\>.csv``.
5. Update documentation (``docs/minquic.md``) with a summary of the changes
   and the observed performance impact.

The modular design ensures that the baseline code remains intact for
reference and that the MINQUIC implementation can be evaluated under identical
network conditions.
