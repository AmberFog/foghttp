#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PendingRequestBlockingReason {
    None,
    GlobalActiveRequests,
    PerOriginActiveRequests,
    PendingQueueOrder,
    Mixed,
}
