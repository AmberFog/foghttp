use super::super::test_control::{DecodeCheckpointTarget, DecodeTestControl};
use super::native_test_support::{NativeClient, NativeServer};
use super::test_fixtures::{gzip, reach_checkpoint, BODY, WATCHDOG};
use crate::errors::FogHttpError;
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::runtime::Builder;

#[test]
fn late_buffered_error_does_not_abort_connection_already_owned_by_another_response() {
    Python::initialize();
    let runtime = Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
        .unwrap();
    let mut encoded = gzip(&BODY);
    let checksum_start = encoded.len() - 8;
    encoded[checksum_start] ^= 1;
    let server = NativeServer::start(encoded);
    runtime.block_on(async {
        let client = Arc::new(NativeClient::new());
        let (control, reached, release) = DecodeTestControl::new(
            DecodeCheckpointTarget::Output { layer: 0, minimum: 1 },
        );
        let control = Arc::new(control);
        let first_client = Arc::clone(&client);
        let first_control = Arc::clone(&control);
        let first_origin = server.url.clone();
        let first = tokio::spawn(async move {
            let ready = first_client.begin(&first_origin, "/encoded").await;
            first_client.complete(ready, &first_origin, Some(&first_control)).await
        });
        let event = reach_checkpoint(reached).await;
        assert!(event.progress.output_bytes > 0);
        let paused = client.metrics.snapshot();
        assert_eq!(paused.active_requests, 1);
        assert_eq!(paused.idle_connections, 1);
        assert_eq!(paused.connections_aborted, 0);
        assert!(paused.buffered_response_bytes > 0);

        let borrowed = match tokio::time::timeout(WATCHDOG, client.begin(&server.url, "/healthy")).await {
            Ok(response) => response,
            Err(error) => {
                let stats = client.metrics.snapshot();
                panic!("borrower blocked after completed HTTP EOF: {error}; active/pending/idle/opened/reused/aborted={:?}; requests={:?}", (stats.active_requests, stats.pending_requests, stats.idle_connections, stats.connections_opened, stats.connections_reused, stats.connections_aborted), server.requests());
            }
        };
        assert_eq!(borrowed.response.headers()["x-connection-id"], "1");
        assert_eq!(client.metrics.snapshot().active_requests, 2);
        assert_eq!(client.metrics.snapshot().connections_reused, 1);
        release.send(()).unwrap();
        let first_result = tokio::time::timeout(WATCHDOG, first).await.unwrap().unwrap();
        let error = match first_result {
            Err(error) => error,
            Ok(response) => { drop(response); panic!("corrupt gzip checksum unexpectedly accepted") }
        };
        Python::attach(|python| assert!(error.get_type(python).is(python.get_type::<FogHttpError>())));
        let failed = client.metrics.snapshot();
        assert_eq!(failed.failed_requests, 1);
        assert_eq!(failed.active_requests, 1);
        assert_eq!(failed.buffered_response_bytes, 0);
        assert_eq!(failed.connections_aborted, 0);
        assert_eq!(failed.response_body_aborted, 1);

        let borrowed = client.complete(borrowed, &server.url, None).await.unwrap();
        assert_eq!(borrowed.content, b"healthy");
        assert_eq!(borrowed.headers.iter().find(|(name, _)| name == "x-connection-id").unwrap().1, "1");
        drop(borrowed);
        let recovery = client.begin(&server.url, "/healthy").await;
        assert_eq!(recovery.response.headers()["x-connection-id"], "1");
        drop(client.complete(recovery, &server.url, None).await.unwrap());
        let final_stats = client.metrics.snapshot();
        assert_eq!(final_stats.total_requests, 3);
        assert_eq!(final_stats.failed_requests, 1);
        assert_eq!(final_stats.active_requests, 0);
        assert_eq!(final_stats.pending_requests, 0);
        assert_eq!(final_stats.buffered_response_bytes, 0);
        assert_eq!(final_stats.connections_opened, 1);
        assert_eq!(final_stats.connections_reused, 2);
        assert_eq!(final_stats.connections_aborted, 0);
        server.assert_single_connection_requests(3);
    });
}

#[test]
fn original_total_is_checked_after_raw_response_construction_before_native_return() {
    use crate::errors::FogHttpTimeoutError;
    use crate::messages::REQUEST_TOTAL_TIMEOUT;
    use std::time::Duration;
    use tokio::sync::oneshot;

    Python::initialize();
    let runtime = Builder::new_multi_thread()
        .worker_threads(1)
        .enable_all()
        .build()
        .unwrap();
    let server = NativeServer::start(gzip(&BODY));
    runtime.block_on(async {
        let client = Arc::new(NativeClient::with_total(2.0));
        let (control, reached, release) =
            DecodeTestControl::new(DecodeCheckpointTarget::NativeReturn);
        let control = Arc::new(control);
        let task_client = Arc::clone(&client);
        let task_control = Arc::clone(&control);
        let origin = server.url.clone();
        let (started_tx, started_rx) = oneshot::channel();
        let task = tokio::spawn(async move {
            let ready = task_client.begin(&origin, "/encoded").await;
            started_tx.send(ready.started).unwrap();
            task_client
                .complete(ready, &origin, Some(&task_control))
                .await
        });
        let event = reach_checkpoint(reached).await;
        assert_eq!(
            event.status,
            crate::core::response::BufferedDecodeStatus::Finished
        );
        let started = started_rx.await.unwrap();
        let paused = client.metrics.snapshot();
        assert_eq!(paused.active_requests, 1);
        assert_eq!(paused.idle_connections, 1);
        assert_eq!(paused.response_body_aborted, 0);
        assert!(paused.buffered_response_bytes > 0);
        tokio::time::sleep(Duration::from_secs(2).saturating_sub(started.elapsed())).await;
        release.send(()).unwrap();
        let result = tokio::time::timeout(WATCHDOG, task).await.unwrap().unwrap();
        let error = match result {
            Err(error) => error,
            Ok(response) => {
                drop(response);
                panic!("native response returned after original total expired")
            }
        };
        Python::attach(|python| {
            assert!(error
                .get_type(python)
                .is(python.get_type::<FogHttpTimeoutError>()));
            let args: (String, String, f64, f64, String, usize) = error
                .value(python)
                .getattr("args")
                .unwrap()
                .extract()
                .unwrap();
            assert_eq!(args.0, REQUEST_TOTAL_TIMEOUT);
            assert_eq!(args.1, "response_body");
            assert!(args.2 >= 2.0);
            assert_eq!(args.3.to_bits(), 2.0_f64.to_bits());
            assert_eq!(args.4, server.url);
            assert_eq!(args.5, 0);
        });
        let failed = client.metrics.snapshot();
        assert_eq!(failed.failed_requests, 1);
        assert_eq!(failed.active_requests, 0);
        assert_eq!(failed.pending_requests, 0);
        assert_eq!(failed.buffered_response_bytes, 0);
        assert_eq!(failed.response_body_aborted, 1);
        assert_eq!(failed.connections_aborted, 0);
        let recovery = client.begin(&server.url, "/healthy").await;
        assert_eq!(recovery.response.headers()["x-connection-id"], "1");
        drop(client.complete(recovery, &server.url, None).await.unwrap());
        assert_eq!(client.metrics.snapshot().connections_reused, 1);
        assert_eq!(client.metrics.snapshot().connections_aborted, 0);
        server.assert_single_connection_requests(2);
    });
}
