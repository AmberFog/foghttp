#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BodyReplayability {
    Replayable,
    NonReplayable,
}

impl BodyReplayability {
    pub fn from_replayable(replayable: bool) -> Self {
        if replayable {
            Self::Replayable
        } else {
            Self::NonReplayable
        }
    }

    pub fn from_buffered_body(body: Option<&[u8]>, replayable: bool) -> Self {
        if body.is_some_and(|content| !content.is_empty()) {
            Self::from_replayable(replayable)
        } else {
            Self::Replayable
        }
    }

    pub fn can_replay(self) -> bool {
        self == Self::Replayable
    }
}
