__all__ = ("NON_TEXT_CODECS", "NON_TEXT_CONTENT_TYPES")


NON_TEXT_CODECS = ("hex_codec", "base64_codec", "zlib_codec")
NON_TEXT_CONTENT_TYPES = tuple(f"text/plain; charset={encoding}" for encoding in NON_TEXT_CODECS)
