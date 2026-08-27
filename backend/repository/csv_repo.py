"""
The CSV files are an implementation of the database described in
docs/data-schema.md, not a format we pass through. Nothing above this file
knows they exist.

One file per vehicle, named in config/vehicles.yaml, resolved against
`data.directory` in config/app.yaml.

Read docs/data-schema.md section 5.2 before implementing.

A configured vehicle with no export file yet is a legitimate state: empty data,
still listed in the fleet filter.
"""
