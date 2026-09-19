# MINQUIC Package

MINQUIC mirrors the ``quic`` package and replaces congestion control with
**MINBBR** (``congestion.py``). See ``docs/minquic.md`` for the algorithm and
``docs/experiments.md`` for comparing it with the QUIC baseline.

```bash
python -m minquic.server
python -m minquic.client --payload-size 5000000 --streams 3 --trace
```
