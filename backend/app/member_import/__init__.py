"""Bringing a gym's member list over from its spreadsheet (CSV or XLSX).

`sheet` reads the file into rows of text, `rows` turns rows and a column mapping into
validated people, and `app.api.member_import` writes them, each row on its own.
"""
