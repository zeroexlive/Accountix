# Reporting has no models by design (Sprint 08): it is a presentation and
# aggregation layer over the other apps' derived reporting services.
# This module exists only so Django treats the app as a normal app
# package; it must stay free of model classes — no tables, no migrations.
