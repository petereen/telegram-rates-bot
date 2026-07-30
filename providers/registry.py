"""Import every production provider exactly once to populate the registry."""

from __future__ import annotations


def register_all_providers() -> None:
    # Imports intentionally live inside this function so API and bot entry
    # points can both initialize the same provider set without side effects
    # during unrelated unit tests.
    import providers.binance  # noqa: F401
    import providers.boc  # noqa: F401
    import providers.capitronbank  # noqa: F401
    import providers.cbr  # noqa: F401
    import providers.mongolbank  # noqa: F401
    import providers.profinance  # noqa: F401
    import providers.rapira  # noqa: F401
    import providers.xe  # noqa: F401
    # Import last so normalized upstream API implementations replace the
    # older one-off CapitronBank registration. MongolBank is intentionally
    # excluded from that module because its official provider uses the BOM
    # endpoint and the community API does not currently publish a snapshot.
    import providers.mongolian_banks  # noqa: F401
