"""Edge adapters: read Home Assistant / external data into engine inputs.

Parsing logic is kept pure and unit-tested; the async Home Assistant fetches are
thin wrappers with lazy HA imports so these modules import without HA present.
"""
