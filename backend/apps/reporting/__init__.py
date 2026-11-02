"""Reporting & UX layer (Sprint 08): dashboard aggregation and exports.

No models and no stored data live here (the app's ``models.py`` is an
empty placeholder module): every figure is derived at request time from
the owning apps' reporting services, which in turn derive from journal
lines and stock movements (ADR-010/012/015/031).
"""
