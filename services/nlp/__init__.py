"""
Phase 2: NLP query understanding.

Public entry point: services.nlp.parser.parse(query) -> StructuredQuery.

This package converts a natural-language real-estate search query into
a structured representation (services.nlp.schema.StructuredQuery). It
does NOT search properties, does NOT resolve locations to coordinates,
and does NOT call Mappls or OSM - see services/mappls_service.py and
services/osm_location_service.py for that (Phase 1), and
routes/search_routes.py for the existing production search (unchanged
by this phase). See docs/PHASE_2_NLP_REPORT.md for the full design.
"""

from services.nlp.parser import parse
from services.nlp.baseline import parse_baseline
from services.nlp.schema import StructuredQuery

__all__ = ["parse", "parse_baseline", "StructuredQuery"]
