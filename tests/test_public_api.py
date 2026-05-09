import foghttp
import foghttp.models
import foghttp.stats


def test_top_level_exports() -> None:
    assert foghttp.Client is not None
    assert foghttp.AsyncClient is not None
    assert foghttp.Headers is not None
    assert foghttp.RequestInfo is not None
    assert foghttp.URL is not None


def test_compatibility_modules_reexport_models() -> None:
    assert foghttp.models.Limits is foghttp.Limits
    assert foghttp.models.Headers is foghttp.Headers
    assert foghttp.models.Response is foghttp.Response
    assert foghttp.models.Timeouts is foghttp.Timeouts
    assert foghttp.models.URL is foghttp.URL
    assert foghttp.stats.PoolStats is foghttp.PoolStats
