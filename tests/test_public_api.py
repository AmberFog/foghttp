import foghttp
import foghttp.methods
import foghttp.models
import foghttp.stats


def test_top_level_exports() -> None:
    assert foghttp.Client is not None
    assert foghttp.AsyncLifecycleDebugConfig is not None
    assert foghttp.AsyncLifecycleDebugRequest is not None
    assert foghttp.AsyncLifecycleDebugRequestMode is not None
    assert foghttp.AsyncLifecycleDebugSnapshot is not None
    assert foghttp.AsyncClient is not None
    assert foghttp.AsyncStreamResponse is not None
    assert foghttp.Headers is not None
    assert foghttp.Request is not None
    assert foghttp.RequestExtensions is not None
    assert foghttp.RequestInfo is not None
    assert foghttp.ResponseBodyBudgetExceededError is not None
    assert foghttp.ResponseBodyTooLargeError is not None
    assert foghttp.StreamResponse is not None
    assert foghttp.TLSConfig is not None
    assert foghttp.TimeoutDiagnostic is not None
    assert foghttp.TimeoutPhase is not None
    assert foghttp.TransportState is not None
    assert foghttp.OriginPressureState is not None
    assert foghttp.URL is not None


def test_compatibility_modules_reexport_models() -> None:
    assert foghttp.models.Limits is foghttp.Limits
    assert foghttp.models.AsyncLifecycleDebugConfig is foghttp.AsyncLifecycleDebugConfig
    assert foghttp.models.AsyncLifecycleDebugRequest is foghttp.AsyncLifecycleDebugRequest
    assert foghttp.models.AsyncLifecycleDebugRequestMode is foghttp.AsyncLifecycleDebugRequestMode
    assert foghttp.models.AsyncLifecycleDebugSnapshot is foghttp.AsyncLifecycleDebugSnapshot
    assert foghttp.models.Headers is foghttp.Headers
    assert foghttp.models.Request is foghttp.Request
    assert foghttp.models.RequestExtensions is foghttp.RequestExtensions
    assert foghttp.models.Response is foghttp.Response
    assert foghttp.models.AsyncStreamResponse is foghttp.AsyncStreamResponse
    assert foghttp.models.StreamResponse is foghttp.StreamResponse
    assert foghttp.models.TLSConfig is foghttp.TLSConfig
    assert foghttp.models.TimeoutDiagnostic is foghttp.TimeoutDiagnostic
    assert foghttp.models.TimeoutPhase is foghttp.TimeoutPhase
    assert foghttp.models.Timeouts is foghttp.Timeouts
    assert foghttp.models.URL is foghttp.URL
    assert foghttp.stats.TransportStats is foghttp.TransportStats


def test_query_method_is_exported() -> None:
    assert foghttp.methods.QUERY == "QUERY"
    assert foghttp.methods.QUERY in foghttp.methods.HTTP_METHODS
    assert foghttp.methods.HTTP_METHODS.count(foghttp.methods.QUERY) == 1
    assert "QUERY" in foghttp.methods.__all__
