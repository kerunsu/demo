# Performance and robustness comparison

No trustworthy before/after production benchmark was available in this audit;
hardware, Runtime and real voice providers were not running. It would be unsafe
to claim improved FPS, latency, CPU, memory or quality.

## Safe observations

- The new session quality endpoint is opt-in and performs no media decoding or
  writes. Hashing is also opt-in because it is an O(file size) read.
- ZIP staging reads each archive entry at most `max_item_bytes + 1`, limits
  entry count, rejects links/traversal and enforces total size before commit.
- Existing recording filenames, codecs, sampling rates, analyzer selection and
  interaction timing were not changed as a performance shortcut.

## Required benchmark

Run on the deployment hardware in browser and Runtime modes: cold startup,
idle CPU/RSS, queue depth, analysis/report latency, Socket reconnect, stop/
flush duration, thread count over a long session and storage growth. Compare
the same course, device profile, sample rate, model and media settings. Record
raw logs and rollback if any user-visible timing or quality changes.
