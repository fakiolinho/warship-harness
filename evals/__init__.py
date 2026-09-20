"""Evals: does the harness behave, as opposed to does it run.

The test suite proves the wiring. It cannot prove that the gate's rules
match what a model actually tries, that the system prompt reliably elicits
STEP lines, or that the judge agrees with a human. Those are behavioural
claims and they need measurement, not assertions.

Offline evals need no API key and run in CI. Online evals call a real
model, cost money, and are opt in.
"""
