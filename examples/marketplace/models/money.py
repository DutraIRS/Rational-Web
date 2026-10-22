def price(cents: int) -> str:
    """``12900`` -> ``"$129.00"``. Money is stored and added up as integer cents, never floats."""
    return f"${cents / 100:,.2f}"
