"""Numbered migrations for the vNext persistence layer.

Each migration is a module named ``NNN_description.py`` with
``upgrade(conn)`` and ``downgrade(conn)`` functions. The functions
take a SQLite connection with the project's frozen PRAGMAs already
applied. The migration is responsible for every DDL and DML change
that advances the schema to the next version.

The numbered migrations are an append-only sequence. Adding a new
migration means adding a new module to this package; the runner
discovers them automatically.

See ADR-0003 (application persistence model).
"""
