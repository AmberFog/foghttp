# FogHTTP benchmark results

- Timestamp: `20260507-002954`
- Python: `3.14.0`
- Platform: `macOS-26.3.1-arm64-arm-64bit-Mach-O`
- Requests/run: `1000`
- Warmup/run: `100`
- Repeats: `2`

## Aggregate

| client | scenario | conc | req/s median | p50 ms | p95 ms | p99 ms | max RSS MB | max threads | max fds | errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| foghttp | post-echo-64k | 100 | 11286.3 | 6.82 | 7.72 | 8.00 | 55.1 | 49 | 42 | 0 |
| httpx | post-echo-64k | 100 | 161.1 | 243.79 | 2486.39 | 3702.85 | 82.2 | 17 | 207 | 0 |
| zapros | post-echo-64k | 100 | 5014.7 | 18.56 | 25.79 | 26.31 | 81.3 | 17 | 27 | 0 |
