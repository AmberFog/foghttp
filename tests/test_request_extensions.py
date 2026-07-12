from typing import TYPE_CHECKING, cast

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET


if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping


def test_request_extensions_are_an_immutable_shallow_snapshot(faker: Faker) -> None:
    request_id, changed_request_id = faker.uuid4(), faker.uuid4()
    tags = faker.words(nb=2)
    source: dict[str, object] = {
        "tests.request_id": request_id,
        "tests.tags": tags,
    }

    request = foghttp.Request(GET, faker.url(), extensions=source)
    source["tests.request_id"] = changed_request_id
    source["tests.extra"] = faker.word()

    assert request.extensions["tests.request_id"] == request_id
    assert request.extensions["tests.tags"] is tags
    assert "tests.extra" not in request.extensions

    mutable_extensions = cast("MutableMapping[str, object]", request.extensions)
    with pytest.raises(TypeError):
        mutable_extensions["tests.request_id"] = changed_request_id


def test_request_extensions_repr_does_not_expose_keys_or_values(faker: Faker) -> None:
    key = f"tests.{faker.word()}"
    value = faker.uuid4()

    representation = repr(foghttp.RequestExtensions({key: value}))

    assert key not in representation
    assert value not in representation
    assert "<1 items>" in representation


def test_requests_without_extensions_reuse_empty_snapshot(faker: Faker) -> None:
    first = foghttp.Request(GET, faker.url())
    second = foghttp.Request(GET, faker.url())
    explicit_empty = foghttp.Request(
        GET,
        faker.url(),
        extensions=foghttp.RequestExtensions(),
    )

    assert first.extensions == {}
    assert first.extensions is second.extensions
    assert first.extensions is explicit_empty.extensions


@pytest.mark.parametrize("invalid_key", [None, 1])
def test_request_extensions_reject_non_string_keys(invalid_key: object, faker: Faker) -> None:
    extensions = cast("Mapping[str, object]", {invalid_key: faker.word()})

    with pytest.raises(TypeError, match="request extension keys must be strings"):
        foghttp.RequestExtensions(extensions)


def test_request_extensions_reject_empty_key(faker: Faker) -> None:
    with pytest.raises(ValueError, match="request extension keys must not be empty"):
        foghttp.RequestExtensions({"": faker.word()})


def test_request_extensions_reject_reserved_namespace(faker: Faker) -> None:
    key = f"FogHTTP.{faker.word()}"

    with pytest.raises(ValueError, match=r"reserved 'foghttp\.' namespace") as exc_info:
        foghttp.RequestExtensions({key: faker.word()})

    assert key not in str(exc_info.value)


def test_request_extensions_reject_non_mapping_source() -> None:
    with pytest.raises(TypeError, match="extensions must be a mapping or None"):
        foghttp.RequestExtensions(cast("object", []))


@pytest.mark.parametrize(
    "invalid_source",
    [pytest.param([], id="list"), pytest.param("", id="string"), pytest.param(0, id="integer")],
)
def test_request_rejects_falsey_non_mapping_extensions(invalid_source: object, faker: Faker) -> None:
    extensions = cast("Mapping[str, object]", invalid_source)

    with pytest.raises(TypeError, match="extensions must be a mapping or None"):
        foghttp.Request(GET, faker.url(), extensions=extensions)
