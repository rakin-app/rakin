"""The Términos de servicio and de encargo a gym accepts in the app (#499).

Their text is `docs/legal/`, built into the image (`/app/legal`) and read from there
at runtime (`app.legal.terms`); each carries its own "Versión" line, and a test holds
these constants equal to them. A change a gym must accept again for gets a new one,
and the titular sees the acceptance page again at their next request (`app.tenancy`).
"""

# The "Versión" line of `docs/legal/terminos-de-servicio.md`.
SERVICE_TERMS_VERSION = "2026-11-20"
# The "Versión" line of `docs/legal/terminos-de-encargo.md`.
PROCESSOR_TERMS_VERSION = "2026-11-20"
