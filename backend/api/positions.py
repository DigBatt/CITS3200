"""
GET /api/positions.

 stored positions for a selection and a period.

Every selected vehicle appears in the response, empty or not, the dashboard must be able to discern data availability.
 A valid query matching nothing is 200 with empty arrays and not 404.

Response shape: docs/api.md.
"""
