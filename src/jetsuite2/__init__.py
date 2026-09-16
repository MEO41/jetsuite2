"""jetsuite2: single-spool centrifugal micro-turbojet design suite.

Design sequence (each a stage module under ``jetsuite2.stages``)::

    requirements -> cycle -> compressor -> turbine -> combustor -> rotor -> mechanical -> layout -> geometry -> cad

Stages are pure functions of a projected slice of the design state (see
``jetsuite2.state``).  The graph re-runs only the stages whose inputs changed.
"""
__version__ = "0.1.0"
