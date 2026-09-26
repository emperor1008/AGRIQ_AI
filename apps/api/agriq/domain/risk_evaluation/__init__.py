"""Risk-evaluation package (Phase 5 §13–17).

Offline evaluation of the Crop Risk Intelligence engine against REAL reference
events. This package is never imported by the farmer-facing request path:

* ``definitions`` — the documented evaluation protocol (event windows,
  false-alert / missed-event definitions, metric definitions, sample minima).
* ``dataset`` — strict loading of operator-supplied reference-event datasets
  with provenance.
* ``metrics`` — metric maths that returns ``insufficient_data`` instead of a
  number when the sample is too small.
* ``evaluate`` — matches issued warnings to documented events and produces the
  overall + per-crop / per-stage / per-district report.

The published state today is honest: unless a real, provanced reference-event
dataset is supplied, every evaluation reports ``insufficient_data``. No metric
is ever fabricated.
"""
