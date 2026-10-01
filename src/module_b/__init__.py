"""Module B — event-driven portfolio stress tester.

Takes high-impact risk signals (from Module A's NLP risk engine) and runs
a portfolio through simplified macro/credit/equity shock scenarios to
estimate loss and attribution by asset class.

Submodules:
    portfolio    — deterministic synthetic portfolio generator
    shocks       — shock scenario library + valuation (simplified) model
    stress_test  — CLI entry point: ``python -m module_b.stress_test``
"""
