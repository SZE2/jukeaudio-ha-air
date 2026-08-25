def test_custom_component_imports():
    """The Juke custom component package imports successfully."""
    import custom_components.jukeaudio_ha  # noqa: F401
