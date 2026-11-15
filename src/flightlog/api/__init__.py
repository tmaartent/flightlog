"""HTTP and CLI entry points. Translate requests into commands, results into responses.

Never imports infrastructure: the adapters it needs (unit of work, database probe) are wired
in by the composition root, create_app, and fetched from app.extensions.
"""
