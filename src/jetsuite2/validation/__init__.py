"""Validation database and method-validation runner.

``cases.py`` holds the reference cases (independent-code maps from
boomsonic_v0, manufacturer datasheets of the 100-1000 N micro-turbojet
fleet, and classical test cases with their literature values) and the
functions that run each analysis method against them and report the error.
No method ships without at least one case here; the error is reported, not
hidden, and is what the uncertainty quantification uses as the model-form
error band.
"""
