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

    pub fn can_replay(self) -> bool {
        self == Self::Replayable
    }
}
