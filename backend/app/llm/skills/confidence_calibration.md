---
name: confidence_calibration
version: 1
description: What a confidence of 30 / 60 / 90 means, so scores are comparable across agents
---
Calibrate confidence to the evidence, not to how strongly you feel:
- 0-30: little or conflicting evidence, or key data is missing. Prefer neutral.
- 30-60: the evidence leans one way, with notable counter-signals.
- 60-80: several independent signals agree and the data is complete.
- 80-95: overwhelming, consistent evidence. Rare.
Never exceed 95. Lower the score for every important input that is missing.
