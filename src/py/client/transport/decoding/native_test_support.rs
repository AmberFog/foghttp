use super::super::test_control::DecodeTestControl;
use crate::core::client::{build_client_with_connection_gate, ClientOptions, ConnectionGate};
use crate::core::headers::{response_headers, HeaderPairs};
use crate::core::metrics::Metrics;
use crate::core::policy::TransportRoute;
use crate::core::response::BufferedBodyBudget;
use crate::py::client::acquire::{AcquireGate, AcquirePermit};
use crate::py::client::transport::context::RawResponseContext;
use crate::py::client::transport::request::{send_current_hop, RequestState, TransportRequest};
use crate::py::client::transport::response::{raw_response, ResponseLifecycleGuards};
use crate::py::client::transport::TransportClients;
use crate::py::response::{RawRequestInfo, RawResponse};
use hyper::body::Incoming;
use hyper::Response;
use pyo3::prelude::*;
use std::io::{BufRead, BufReader, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const TOTAL_TIMEOUT: f64 = 30.0;
const BODY_LIMIT: usize = super::test_fixtures::BODY_SIZE;

#[derive(Default)]
struct ServerState {
    stopped: AtomicBool,
    connections: AtomicUsize,
    requests: Mutex<Vec<(usize, String)>>,
    sockets: Mutex<Vec<TcpStream>>,
}

pub(super) struct NativeServer {
    pub url: String,
    state: Arc<ServerState>,
    thread: Option<JoinHandle<()>>,
}

impl NativeServer {
    pub fn start(encoded: Vec<u8>) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        listener.set_nonblocking(true).unwrap();
        let state = Arc::new(ServerState::default());
        let worker_state = Arc::clone(&state);
        let thread = thread::spawn(move || {
            let mut workers = Vec::new();
            while !worker_state.stopped.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((socket, _peer)) => {
                        socket.set_nonblocking(false).unwrap();
                        socket
                            .set_read_timeout(Some(Duration::from_secs(10)))
                            .unwrap();
                        worker_state
                            .sockets
                            .lock()
                            .unwrap()
                            .push(socket.try_clone().unwrap());
                        let state = Arc::clone(&worker_state);
                        let encoded = encoded.clone();
                        workers.push(thread::spawn(move || {
                            serve_connection(socket, &encoded, &state);
                        }));
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1));
                    }
                    Err(error) => panic!("native test listener failed: {error}"),
                }
            }
            for worker in workers {
                worker.join().unwrap();
            }
        });
        Self {
            url,
            state,
            thread: Some(thread),
        }
    }

    pub fn requests(&self) -> Vec<(usize, String)> {
        self.state.requests.lock().unwrap().clone()
    }

    pub fn assert_single_connection_requests(&self, count: usize) {
        assert_eq!(self.state.connections.load(Ordering::SeqCst), 1);
        let requests = self.state.requests.lock().unwrap();
        assert_eq!(requests.len(), count);
        assert!(requests.iter().all(|(connection, _path)| *connection == 1));
    }
}

impl Drop for NativeServer {
    fn drop(&mut self) {
        self.state.stopped.store(true, Ordering::SeqCst);
        for socket in self.state.sockets.lock().unwrap().iter() {
            let _shutdown = socket.shutdown(Shutdown::Both);
        }
        self.thread.take().unwrap().join().unwrap();
    }
}

fn serve_connection(mut socket: TcpStream, encoded: &[u8], state: &ServerState) {
    let connection = state.connections.fetch_add(1, Ordering::SeqCst) + 1;
    let mut reader = BufReader::new(socket.try_clone().unwrap());
    loop {
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) | Err(_) => return,
            Ok(_) => {}
        }
        let Some(path) = line.split_whitespace().nth(1).map(str::to_owned) else {
            return;
        };
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => return,
                Ok(_) if line == "\r\n" => break,
                Ok(_) => {}
            }
        }
        state
            .requests
            .lock()
            .unwrap()
            .push((connection, path.clone()));
        let (body, coding) = if path == "/encoded" {
            (encoded, "content-encoding: gzip\r\n")
        } else {
            (b"healthy".as_slice(), "")
        };
        let header = format!(
            "HTTP/1.1 200 OK\r\ncontent-length: {}\r\nx-connection-id: {connection}\r\n{coding}\r\n",
            body.len(),
        );
        if socket
            .write_all(header.as_bytes())
            .and_then(|()| socket.write_all(body))
            .is_err()
        {
            return;
        }
        if socket.flush().is_err() {
            return;
        }
    }
}

pub(super) struct NativeClient {
    pub metrics: Arc<Metrics>,
    clients: TransportClients,
    acquire: AcquireGate,
    budget: BufferedBodyBudget,
    buffered_decoders: Arc<tokio::sync::Semaphore>,
    total_timeout: f64,
}

pub(super) struct ReadyResponse {
    pub response: Response<Incoming>,
    request: RawRequestInfo,
    headers: HeaderPairs,
    lifecycle: ResponseLifecycleGuards,
    permit: AcquirePermit,
    pub started: Instant,
}

impl NativeClient {
    pub fn new() -> Self {
        Self::with_total(TOTAL_TIMEOUT)
    }

    pub fn with_total(total_timeout: f64) -> Self {
        let metrics = Arc::new(Metrics::default());
        let client = build_client_with_connection_gate(
            &ClientOptions {
                max_idle_connections_per_host: 1,
                idle_timeout: 30.0,
                keepalive: true,
                connect_timeout: 10.0,
                ca_certificates: Vec::new(),
                trust_webpki_roots: true,
                http_proxy_url: None,
                https_proxy_url: None,
                https_proxy_authorization: None,
                ssrf_policy: None,
            },
            Arc::clone(&metrics),
            ConnectionGate::new(Some(1), Some(1)),
            None,
        )
        .unwrap();
        Self {
            clients: TransportClients::new(client, None),
            acquire: AcquireGate::new(2, None, 0, Arc::clone(&metrics)),
            budget: BufferedBodyBudget::new(Some(BODY_LIMIT * 4), Arc::clone(&metrics)),
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
            metrics,
            total_timeout,
        }
    }

    pub async fn begin(&self, origin: &str, path: &str) -> ReadyResponse {
        let started = Instant::now();
        self.metrics.request_started();
        let permit = self.acquire.acquire(origin, 10.0, 0).await.unwrap();
        let mut state = RequestState::try_from(self.request(origin, path)).unwrap();
        let (response, request, connection) = send_current_hop(
            &self.clients,
            &mut state,
            origin,
            0,
            10.0,
            started,
            TransportRoute::Direct,
        )
        .await
        .unwrap()
        .unwrap();
        let lifecycle = ResponseLifecycleGuards::new(
            &response,
            connection,
            &self.metrics,
            &permit.origin_metrics(),
        );
        let headers = response_headers(response.headers());
        ReadyResponse {
            response,
            request,
            headers,
            lifecycle,
            permit,
            started,
        }
    }

    pub async fn complete(
        &self,
        ready: ReadyResponse,
        origin: &str,
        control: Option<&DecodeTestControl>,
    ) -> PyResult<RawResponse> {
        let context = RawResponseContext {
            started: ready.started,
            total_timeout: self.total_timeout,
            read_timeout: 10.0,
            max_response_body_size: Some(BODY_LIMIT),
            buffered_body_budget: self.budget.clone(),
            buffered_decoders: Arc::clone(&self.buffered_decoders),
            origin,
            redirect_hop: 0,
            decode_checkpoint: control,
        };
        let result = raw_response(
            ready.response,
            ready.request,
            ready.headers,
            ready.lifecycle,
            context,
        )
        .await;
        drop(ready.permit);
        self.metrics.request_finished(result.is_err());
        result
    }

    fn request(&self, origin: &str, path: &str) -> TransportRequest {
        TransportRequest {
            method: "GET".to_owned(),
            url: format!("{origin}{path}"),
            headers: Vec::new(),
            auth_override_headers: None,
            auth_removed_headers: Vec::new(),
            body: None,
            body_stream: None,
            body_replayable: true,
            use_proxy_transport: false,
            proxy_policy: "direct".to_owned(),
            proxy_authorization: None,
            total_timeout: self.total_timeout,
            read_timeout: 10.0,
            write_timeout: 10.0,
            max_response_body_size: Some(BODY_LIMIT),
            buffered_body_budget: self.budget.clone(),
            buffered_decoders: Arc::clone(&self.buffered_decoders),
            follow_redirects: false,
            max_redirects: 0,
            retry_policy: None,
            ssrf_policy: None,
            cookie_jar: None,
            auth: None,
            policy_hooks: None,
            extensions: None,
        }
    }
}
