import foghttp
import foghttp.errors as errors_module
import foghttp.methods as methods_module
import foghttp.models as models_module
import foghttp.policy as policy_module
import foghttp.stats as stats_module
import foghttp.types as types_module


def test_top_level_exports() -> None:
    assert foghttp.Client is not None
    assert foghttp.ConfigurationError is errors_module.ConfigurationError
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
    assert foghttp.RetryAttempt is not None
    assert foghttp.RetryConditions is not None
    assert foghttp.RetryPolicy is not None
    assert foghttp.RetryTrace is not None
    assert foghttp.RetryTraceOutcome is not None
    assert foghttp.SSRFError is not None
    assert foghttp.SSRFPolicy is not None
    assert foghttp.SSRFViolationReason is not None
    assert foghttp.StreamResponse is not None
    assert foghttp.TLSConfig is not None
    assert foghttp.TimeoutDiagnostic is not None
    assert foghttp.TimeoutPhase is not None
    assert foghttp.TransportState is not None
    assert foghttp.OriginPressureState is not None
    assert foghttp.URL is not None
    assert issubclass(foghttp.ConfigurationError, foghttp.FogHTTPError)
    assert issubclass(foghttp.ConfigurationError, ValueError)
    assert issubclass(foghttp.NetworkError, foghttp.RequestError)
    assert issubclass(foghttp.SSRFError, foghttp.RequestError)


def test_compatibility_modules_reexport_models() -> None:
    assert models_module.Limits is foghttp.Limits
    assert models_module.AsyncLifecycleDebugConfig is foghttp.AsyncLifecycleDebugConfig
    assert models_module.AsyncLifecycleDebugRequest is foghttp.AsyncLifecycleDebugRequest
    assert models_module.AsyncLifecycleDebugRequestMode is foghttp.AsyncLifecycleDebugRequestMode
    assert models_module.AsyncLifecycleDebugSnapshot is foghttp.AsyncLifecycleDebugSnapshot
    assert models_module.Headers is foghttp.Headers
    assert models_module.Request is foghttp.Request
    assert models_module.RequestExtensions is foghttp.RequestExtensions
    assert models_module.Response is foghttp.Response
    assert models_module.AsyncStreamResponse is foghttp.AsyncStreamResponse
    assert models_module.StreamResponse is foghttp.StreamResponse
    assert models_module.TLSConfig is foghttp.TLSConfig
    assert models_module.TimeoutDiagnostic is foghttp.TimeoutDiagnostic
    assert models_module.TimeoutPhase is foghttp.TimeoutPhase
    assert models_module.Timeouts is foghttp.Timeouts
    assert models_module.URL is foghttp.URL
    assert stats_module.TransportStats is foghttp.TransportStats


def test_query_method_is_exported() -> None:
    assert methods_module.QUERY == "QUERY"
    assert methods_module.QUERY in methods_module.HTTP_METHODS
    assert methods_module.HTTP_METHODS.count(methods_module.QUERY) == 1
    assert "QUERY" in methods_module.__all__


def test_public_typing_protocols_do_not_open_transport_adapters() -> None:
    assert types_module.RequestProtocol is not None
    assert types_module.ResponseProtocol is not None
    assert types_module.BufferedResponseProtocol is not None
    assert types_module.StreamResponseProtocol is not None
    assert types_module.AsyncStreamResponseProtocol is not None
    assert not hasattr(foghttp, "SyncTransport")
    assert not hasattr(foghttp, "AsyncTransport")
    assert not hasattr(types_module, "SyncTransport")
    assert not hasattr(types_module, "AsyncTransport")


def test_policy_contracts_are_identical_at_the_package_root() -> None:
    assert foghttp.TransportPolicyBodyState is policy_module.TransportPolicyBodyState
    assert foghttp.TransportPolicyHooks is policy_module.TransportPolicyHooks
    assert foghttp.TransportPolicyRequest is policy_module.TransportPolicyRequest
    assert foghttp.TransportPolicyRequestHook is policy_module.TransportPolicyRequestHook
    assert foghttp.TransportPolicyResponse is policy_module.TransportPolicyResponse
    assert foghttp.TransportPolicyResponseHook is policy_module.TransportPolicyResponseHook
