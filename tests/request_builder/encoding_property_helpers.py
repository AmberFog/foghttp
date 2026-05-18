__all__ = (
    "FIELD_MAPPING",
    "FIELD_PAIRS",
    "FIELD_PROPERTY_EXAMPLES",
    "PATH_SEGMENTS",
    "QUERY_FRAGMENT",
    "REQUEST_URL",
    "URL_PROPERTY_EXAMPLES",
    "decoded_body_pairs",
    "decoded_query_pairs",
    "expected_pairs",
    "url_with_query",
)

from urllib.parse import parse_qsl, urlencode

from hypothesis import strategies as st

from foghttp.types import QueryParams, RequestData


URL_PROPERTY_EXAMPLES = 80
FIELD_PROPERTY_EXAMPLES = 120
QUERY_FRAGMENT = "results"
REQUEST_URL = f"https://example.com/search#{QUERY_FRAGMENT}"

FIELD_ALPHABET = st.characters(
    blacklist_categories=("Cc", "Cs"),
    blacklist_characters="\x00",
)
FIELD_NAME = st.text(FIELD_ALPHABET, min_size=1, max_size=12)
FIELD_TEXT = st.text(FIELD_ALPHABET, max_size=16)
FIELD_SCALAR = st.one_of(
    FIELD_TEXT,
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)
FIELD_VALUE = st.one_of(FIELD_SCALAR, st.lists(FIELD_SCALAR, max_size=3))
FIELD_PAIRS = st.lists(st.tuples(FIELD_NAME, FIELD_VALUE), max_size=8)
FIELD_MAPPING = st.dictionaries(FIELD_NAME, FIELD_VALUE, max_size=8)
PATH_SEGMENT = st.text(
    st.characters(whitelist_categories=("Ll", "Lu"), whitelist_characters="-_0123456789"),
    min_size=1,
    max_size=10,
)
PATH_SEGMENTS = st.lists(PATH_SEGMENT, min_size=1, max_size=3)


def url_with_query(url: str, pairs: QueryParams) -> str:
    query = urlencode(pairs, doseq=True)
    if not query:
        return url

    prefix, fragment = url.split("#", maxsplit=1)
    separator = "&" if "?" in prefix else "?"
    return f"{prefix}{separator}{query}#{fragment}"


def expected_pairs(data: RequestData) -> list[tuple[str, str]]:
    return decoded_query_pairs(urlencode(data, doseq=True))


def decoded_query_pairs(query: str) -> list[tuple[str, str]]:
    return parse_qsl(query, keep_blank_values=True)


def decoded_body_pairs(content: bytes | None) -> list[tuple[str, str]]:
    if content is None:
        msg = "expected encoded request body content"
        raise AssertionError(msg)
    return decoded_query_pairs(content.decode("utf-8"))
