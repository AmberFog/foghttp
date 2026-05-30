#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponseBodyLifecycleOutcome {
    ReuseEligible,
    Closed,
    Aborted,
}
