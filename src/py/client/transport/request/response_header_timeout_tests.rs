use super::{await_response_headers, captured_connection_guard, CapturedConnectionUse};
use crate::core::client::buffered_request_body;
use hyper::Request;
use hyper_util::client::legacy::connect::capture_connection;
use std::future::{poll_fn, Future};
use std::task::Poll;
use std::time::Duration;

#[test]
fn required_capture_without_connection_assignment_fails_closed() {
    let mut request = Request::new(());
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let captured_connection =
        CapturedConnectionUse::new(capture_connection(&mut request), None, None, completion);

    let result = captured_connection_guard(Some(captured_connection));

    assert!(result.is_err());
}
use tokio::runtime::Builder;

#[test]
fn total_timeout_survives_exhausted_cooperative_budget() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();

    runtime.block_on(async {
        let mut polls = 0;
        let mut response = Box::pin(poll_fn(move |context| {
            polls += 1;
            if polls > 1_024 {
                return Poll::Ready(());
            }
            loop {
                let mut consume_budget = Box::pin(tokio::task::consume_budget());
                match consume_budget.as_mut().poll(context) {
                    Poll::Ready(()) => {}
                    Poll::Pending => return Poll::Pending,
                }
            }
        }));
        let mut capture_request = Request::new(());
        let (_body, request_body_completion) = buffered_request_body(None);
        let mut captured_connection = Some(CapturedConnectionUse::new(
            capture_connection(&mut capture_request),
            None,
            None,
            request_body_completion,
        ));
        let expired_deadline = tokio::time::Instant::now()
            .checked_sub(Duration::from_millis(1))
            .expect("test deadline remains representable");

        let result = await_response_headers(
            response.as_mut(),
            &mut captured_connection,
            None,
            expired_deadline,
        )
        .await;

        assert!(result.is_err());
    });
}
