"""Presentation layer — PySide6 widgets, views, and theming.

Rules for this package:
- The only package where ``PySide6`` may be imported.
- Views render state and forward user intent to the application layer;
  they contain no business rules and no DSP math.
"""
