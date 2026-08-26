# Testing and acceptance

The canonical collection is explicitly `python -m pytest tests -q`; it must not
discover `temp_clone/` or adjacent workspaces. No-hardware CI uses fake clock,
fake camera/microphone/Runtime, temporary session roots and monkeypatches. It
must not skip a real required-device assertion or alter product defaults.

Required automated gates:

- route/Socket snapshot and field-level fixture regression;
- golden training flow, cancel, idempotency, rooms, busy mutex and continuous
  recording;
- upload checksum/archive metadata and late Runtime upload;
- report review transition idempotency: one ready notification per draft,
  published state survives repeated generation, and teacher status polling
  never regenerates or reopens a dismissed/published Server prompt;
- report projection: the three demo courses (mimic, pairing and ordering) have explicit
  coverage status, disabled historical courses are absent, missing enabled
  courses never become zero, course-vs-target visuals contain no raw IDs or
  formula/error codes, and high-performing sessions still receive evidence-
  linked consolidation recommendations; the former radar is absent, the active
  mimic/attention, pairing and ordering abilities use percentage bars with a visible target and percentage-point
  gap, legacy recommendation bodies are not duplicated, unknown internal
  limitation codes are replaced by teacher-readable wording, and Server review
  save preserves unchanged structured recommendation fields;
- 0/1/N registry, stable track filenames, validator/timebase and read-only
  quality report; Server camera confirmation consumes a recent discovery result
  and discovery never reopens an index already owned by the preview broker;
- readable session/behavior directory parity, side-effect-free path lookup and
  preflight reservation, no empty UUID directory on failure/cancel, legacy UUID
  behavior lookup, and metadata finalization that preserves `tracks[]`;
- model mock/real selection, browser-only dialogue pause/restart and V2
  profile publish/deploy/resolve/fallback;
- realtime phrase library selection, custom additions, per-course isolation,
  non-empty slots and ordering rule variants;
- Server-managed course preset create/edit/delete, ordered course expansion,
  default promotion, corrupt-file fail-closed behavior, invalid/empty-course
  rejection, teacher/Server UI wiring to the shared API, and direct whole-course
  checkboxes without repeated item images for every quick-assessment preset
  course, including after navigating into mimic/pairing/ordering categories;
- demo course-scope fail-closed behavior, production/config/Robot catalog
  filtering, mimic/pairing/ordering default preset and sync catalog, plus
  mimic/pairing/ordering report scores, dimensions and recommendations;
- packaged MediaPipe mimic target extraction, action-joint and mirror-aware
  similarity, visibility rejection, continuous multi-frame/hold gating,
  prompt-audio reset, exact-session result delivery, and one full
  praise/rating/audit package per training/question/item;
- naming/onomatopoeia keyword re-arm after hints, configured homophone/near-
  sound matching, sleeping course-answer misses that cannot fall through into
  a blocking general-dialogue behavior, and awake or explicit-wake remainder
  misses that do reach the dialogue reply; onomatopoeia LLM context explicitly
  requires vocal imitation and forbids picture-selection instructions;
- child dialogue must contain no WAV upload, local-model health probe or FunASR
  dependency; browser transcripts remain buffered during TTS and loudspeaker
  echoes are rejected without dropping a distinct answer; visible child/Maimai
  bubbles persist in order to the matching readable session directory with
  recording-aligned timestamps and atomic replacement;
- child screen input counts exactly one trusted primary `pointerdown` per mouse,
  touch or pen action; it records both pixel and normalized coordinates on the
  main page and committed same-origin interactive iframe, ignores synthetic,
  right-button and staging-frame events, persists no DOM text/input value, and
  distinguishes tracked zero from historical `NOT_COLLECTED`. Summary tests
  cover `clickId` deduplication, per-question counts and first-click latency;
- pairing/ordering assessment versus intervention policies, teacher “下一题”
  separation and repeat-click suppression, committed-frame-only question
  readiness, centred prompt focus, correlated speech-ended input gating and
  reduced-motion support; fixed-size horizontal cards, rounded clipping and
  restored hint/dim/wrong/correct/flip state hooks are source-regressed and
  manually screenshot at 1024×600, 1366×768 and 1920×1080 including five options;
- Runtime/local-OSC foreground replacement cancels an in-flight idle transition
  without a blocking join; the next motion starts inside the bounded unit-test
  latency, completed behaviors retain the final pose for the short default idle
  buffer, and the idle speed multiplier remains shared across modes;
- persisted browser speech rate accepts `0.5..2.0`, defaults old files to
  `0.88`, is present on every browser-TTS payload and is applied by the child to
  the next utterance; the Server control has no confirmation dialog;
- teacher manual wake/close and panel visibility bypass login/lease gating but
  still reject inactive, mismatched or child-offline sessions, scope child
  events to the exact room, echo `requestId`, never emit speech and always
  unlock buttons on ACK/disconnect/watchdog; wake also starts/resumes child
  browser recognition, reports its microphone state to the teacher, carries the
  committed question ID on the first and subsequent transcripts, remains awake
  across multiple turns, and same-question target/option enrichment cannot
  cancel wake;
- teacher hide/show uses a real child-panel hidden state that cannot be
  overridden by the panel's base CSS; the ordering child page omits the
  redundant helper caption above the actual rule;
- global attention/reward behavior ownership, Server phrase/action/expression/
  lower-screen configuration, playable-MP4 filtering, automatic-praise
  animation barriers and per-child teacher selection persistence;
- Robot Runtime release consistency (manifest size/SHA-256/embedded VERSION),
  rejection of a stale `latest` alias, lightweight-update selection, downgrade
  prevention, interrupted-download resume, verified executable staging and
  verified `/child` browser recovery after packaged startup/update;
- batch files/ZIP, malformed entries, duplicates, conflicts, rollback and
  asset-reference protection.

Required manual gates remain separate: real browser permissions and three-page
visual comparison; Robot Runtime/DollSer; 0/1/N physical ambient cameras and
microphones; unplug/busy/unwritable disk/Runtime restart; long-run resource
release; real ASR/LLM/TTS. A source test or fake protocol cannot substitute for
these gates.

Current 2026-08-24 evidence: `python -m pytest tests -q` passes 503 tests;
teacher `npm.cmd run build` succeeds; the 8080 teacher entry and hashed assets
return HTTP 200. The in-app browser passed the real `djt` session, student and
course selection, one normal prepare and one double-click prepare. Both reached
course selection without a dialog; Back cancelled each prepared workflow, and
the final lease file contained no lease. Browser console warnings/errors were
empty. This is not a full class or hardware pass: the child and Runtime were
offline, so start-course, COM3 motion, speech/expression/child synchronization,
finish, reconnect, Runtime restart and soak scenarios remain manual gates.

The Server-managed course preset addition passed real-browser checks against
8080: the preset editor loaded the seeded five-course default, exposed ordered
add/remove controls, and opened a new unsaved preset without mutating the
configuration. The teacher assessment selector displayed that default in its
dropdown and expanded the five courses to eight current items. The Vite-only
ControlPage preview verified the revised attention/reward cards and nested
reward-animation selector without starting a training session.

The interaction-latency addition is covered by deterministic correlation,
percentile, Markdown export, exact modality callback and Server console wiring
tests, including reused-training media isolation and safe recovery of old
misplaced rows. JavaScript syntax checks pass for the child timing fields and
latency dashboard. A Flask read-only request verified the Server page and the
real `djt-2-20260823-4` catalog/report path; the report recovered 881 legacy
rows by exact media ID without mixing the other retries. The page was not
driven through a live browser, and real cross-machine RTT, microphone/VAD,
media decode and Robot Runtime latency remain explicit manual measurements
described in `INTERACTION_LATENCY.md`.

Robot release evidence for `20260824-0036-DJT823`: the full-install and
lightweight-update ZIPs both pass central-directory/CRC checks, SHA-256, exact
size, embedded VERSION and child-recovery sidecar validation. The prior package
passed an isolated packaged-EXE start; live Flask requests advertise this exact
version and return HTTP 206 for both full and update packages. This build's
process launch was not repeated because the local execution policy rejected the
bounded cleanup step.
Physical in-place replacement of a running classroom Robot Runtime remains a
robot-machine manual gate.

Current 2026-08-25 report-redesign evidence: `python -m pytest tests -q`
passes 535 tests; the teacher production build succeeds. The in-app browser
checked the real published `djt` report at 1280×720 in both landscape and
portrait layouts and a historical PARTIAL report with only 1/5 evaluated
courses. Percentage bars, the 70% target marker, percentage-point gap,
“未评估” state, four-part analysis and legacy recommendation projection were
visible without horizontal overflow; browser logs contained no warning or
error from the report page.

Current 2026-08-25 demo-course-scope evidence: the repository virtual
environment runs `python -m pytest tests -q` with 548 passing tests, and the
teacher production build succeeds. An isolated live Server on port 8081 loaded
the packaged pose model at threshold 0.72; read-only smoke requests returned
course IDs `[1, 9, 10]`, types `mimic/pairing/ordering` and the available
default preset `[1, 9, 10]`. The in-app browser loaded the production teacher
bundle and child page. The packaged model detected all 33 points on both real
mimic cards, scored the two different cards at about 0.262, and accepted the
same card only after four frames/654ms. Physical child-camera motion, robot
motion/TTS and teacher rating remain deployment-machine manual gates.
