use std::collections::HashMap;
use std::sync::{Arc, Mutex, PoisonError, Weak};
use tokio::sync::Semaphore;

const ORIGIN_GATE_CLEANUP_THRESHOLD: usize = 1024;

#[derive(Clone)]
pub struct OriginGates {
    max_active_requests_per_origin: usize,
    semaphores: Arc<Mutex<HashMap<String, Weak<Semaphore>>>>,
}

impl OriginGates {
    pub fn new(max_active_requests_per_origin: usize) -> Self {
        Self {
            max_active_requests_per_origin,
            semaphores: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn semaphore(&self, origin: &str) -> Arc<Semaphore> {
        let mut semaphores = self.lock_semaphores();
        if let Some(semaphore) = semaphores.get(origin).and_then(Weak::upgrade) {
            return semaphore;
        }

        if semaphores.len() >= ORIGIN_GATE_CLEANUP_THRESHOLD {
            semaphores.retain(|_origin, semaphore| semaphore.strong_count() > 0);
        }

        let semaphore = Arc::new(Semaphore::new(self.max_active_requests_per_origin));
        semaphores.insert(origin.to_owned(), Arc::downgrade(&semaphore));
        semaphore
    }

    fn lock_semaphores(&self) -> std::sync::MutexGuard<'_, HashMap<String, Weak<Semaphore>>> {
        self.semaphores
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}
