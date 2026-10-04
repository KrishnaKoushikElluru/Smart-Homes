"""External (non-SmartHomes-owned) property search providers.

Every module here returns TRANSIENT, normalized Python dicts for a
single search request - never persisted to MongoDB, never merged into
the `properties` collection, never embedded into the production
SigLIP2 index. See square_yards_service.py's module docstring for the
full architecture rationale.
"""
