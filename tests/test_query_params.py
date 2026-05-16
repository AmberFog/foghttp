import foghttp
from foghttp.url import merge_params


def test_query_params_accept_mapping_scalar_values() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params({"q": "fog", "page": 2, "enabled": True})

    assert str(merged) == "https://example.com/search?q=fog&page=2&enabled=True"


def test_query_params_accept_mapping_sequence_values() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params({"tag": ["rust", "python"]})

    assert str(merged) == "https://example.com/search?tag=rust&tag=python"


def test_query_params_accept_pairs_and_preserve_repeated_key_order() -> None:
    url = foghttp.URL("https://example.com/search")
    params = [
        ("tag", "rust"),
        ("tag", "python"),
        ("sort", "recent"),
    ]

    merged = url.with_params(params)

    assert str(merged) == "https://example.com/search?tag=rust&tag=python&sort=recent"


def test_query_params_accept_pair_sequence_values() -> None:
    url = foghttp.URL("https://example.com/search")
    params = (
        ("tag", ("rust", "python")),
        ("sort", "recent"),
    )

    merged = url.with_params(params)

    assert str(merged) == "https://example.com/search?tag=rust&tag=python&sort=recent"


def test_query_params_accept_raw_query_string() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params("tag=rust&tag=python")

    assert str(merged) == "https://example.com/search?tag=rust&tag=python"


def test_query_params_accept_raw_query_string_with_leading_question_mark() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params("?debug=1&tag=rust")

    assert str(merged) == "https://example.com/search?debug=1&tag=rust"


def test_query_params_preserve_existing_query_and_fragment() -> None:
    url = foghttp.URL("https://example.com/search?q=fog#results")

    merged = url.with_params([("tag", "rust"), ("tag", "python")])

    assert str(merged) == "https://example.com/search?q=fog&tag=rust&tag=python#results"
    assert merge_params(url, "page=2") == "https://example.com/search?q=fog&page=2#results"


def test_query_params_percent_encode_mapping_values() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params(
        {
            "city": "M\u00fcnchen",
            "phrase": "fog http",
            "reserved": "a&b=c",
        },
    )

    assert str(merged) == "https://example.com/search?city=M%C3%BCnchen&phrase=fog+http&reserved=a%26b%3Dc"


def test_query_params_keep_raw_query_string_already_encoded() -> None:
    url = foghttp.URL("https://example.com/search")

    merged = url.with_params("city=M%C3%BCnchen&reserved=a%26b")

    assert str(merged) == "https://example.com/search?city=M%C3%BCnchen&reserved=a%26b"


def test_query_params_do_not_mutate_user_inputs() -> None:
    mapping = {"tag": ["rust", "python"]}
    pairs = [("tag", ["rust", "python"])]

    foghttp.URL("https://example.com/search").with_params(mapping)
    foghttp.URL("https://example.com/search").with_params(pairs)

    assert mapping == {"tag": ["rust", "python"]}
    assert pairs == [("tag", ["rust", "python"])]
