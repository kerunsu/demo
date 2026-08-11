# AI Coding Agent Instructions for Education Training System

## Project Overview
Real-time education training system for special needs children with teacher/student interfaces. Flask backend (app.py) with WebSocket communication, SQLAlchemy ORM, real-time pose/speech analysis via MediaPipe, and multi-modal pipelines. Includes robot arm integration (E.I.Art Doll) controlled via OSC.

## Architecture Essentials

### Core Pattern: Plugin-Based Analysis Framework
- **Registry System**: Auto-register at startup via `app/core/auto_register.py` → `auto_register()`
- **Dual Mode Support**: Toggle via `config/analyzers.yaml` (copy from `.example`) or `USE_REAL_ANALYZERS=true` env var
  - Mock mode: Fast, predictable testing with synthesized data
  - Real mode: MediaPipe pose detection, requires GPU/CPU resources
- **Three Analysis Modes**:
  - **Type A (Realtime)**: Per-frame pose/speech matching, instant scores
  - **Type B (Window)**: Sliding window attention (1-second intervals via `WindowAnalysisScheduler`)
  - **Type C (Session)**: End-of-session cumulative stats via `SessionAccumulator`

### Data Flow (Critical Path)
```
Teacher:play_resource → SessionManager:create_session → Child:start_recording
Child:video_frame/audio_chunk → MediaService queue → FeedbackService:WebSocket push
├─ Video/audio saved to storage/recordings/
├─ AnalysisService spawns Type A/B/C pipelines
├─ VisionPipeline(pose_analyzer→pose_matcher) or AudioPipeline(speech_analyzer→speech_matcher)
├─ Results → TriggerFactory → ActionExecutor (emit events)
└─ Teacher receives match_result/attention_update/session_summary
```

### Service Boundaries  
- **SessionManager** (`app/session/`): CRUD, state transitions (CREATED→RECORDING→ANALYZING→COMPLETED), thread-safe
- **MediaService** (`app/services/media_service.py`): Consumes video/audio queues, persists files, triggers analysis
- **AnalysisService** (`app/services/analysis_service.py`): Core orchestrator—manages pipelines, buffers, accumulators, triggers
- **FeedbackService** (`app/services/feedback_service.py`): WebSocket event emission to teacher/child (triggered by ActionExecutor)

## Configuration Management

### Analyzer Configuration Priority (High to Low)
1. **Environment**: `USE_REAL_ANALYZERS=true`, `VIDEO_FPS=30` (immediate override)
2. **YAML**: `config/analyzers.yaml` (per-analyzer mode, sample_rate, thresholds)
3. **Defaults**: `app/core/config_manager.py` → `ConfigManager.get_analyzer_config(name)`

**Example YAML** (copy from `analyzers.yaml.example`):
```yaml
global:
  mode: mock  # or 'real'
analyzers:
  pose:
    mode: real  # per-analyzer override
    sample_rate: 0.05  # analyze 5% of frames
    min_detection_confidence: 0.5
```

### Sampling Control (Performance Critical)
- **Purpose**: Reduce computation by analyzing only selected frames
- **Mechanism**: `BaseAnalyzer.should_analyze()` checks `_frame_counter % int(1/sample_rate)`
- **Usage**: Always call `analyzer.analyze_with_sampling(frame)` NOT `analyze(frame)` in pipelines
- **Example**: `sample_rate=0.01` → 1 in 100 frames analyzed
- **Frame Counter**: Separate per analyzer; resets on session start

## Key Workflows

### Adding a New Analyzer
1. Create in `app/core/vision/` or `app/core/audio/` inheriting `BaseVisionAnalyzer` or `BaseAudioAnalyzer`
2. Implement `analyze_frame(frame, context)` or `analyze_chunk(chunk, context)` returning `AnalysisResult`
3. Register in `app/core/auto_register.py`: `AnalyzerRegistry.register_analyzer('name', mock_cls=..., real_cls=...)`
4. Add YAML config: `config/analyzers.yaml` under `analyzers.name`
5. Test: `enable_mock_analyzers()` from `app.core.config` for unit tests

### Adding a New Matcher
1. Create in `app/core/matchers/` inheriting `BaseMatcher`
2. Implement `match(features1, features2, context)` returning `MatchResult(score, confidence)`
3. Register via `auto_register()` in same pattern as analyzers
4. **CRITICAL**: Always handle both Real keypoint format (`visibility`) and Mock format (`confidence`)
   - Use `kp.get('confidence', kp.get('visibility', 1.0))` to safely access either field
   - See [BUGFIX_confidence字段错误.md](BUGFIX_confidence字段错误.md) for details on this common pitfall

### Database Initialization (First-Time Setup)

**Windows PowerShell Commands**:
```powershell
# Step 1: Create tables and default admin account (admin/admin123)
python database/init_db.py

# Step 2: Migrate legacy JSON courses to database
python database/migrate_courses.py

# Step 3: Import course resources with mapping
# ALWAYS dry-run first (input 'd' when prompted)
python database/import_course_resources.py

# Step 4: Optional - generate test data for development
python database/generate_sample_data.py
```

**Course Resource Import Details** (see [课程资源导入使用指南.md](课程资源导入使用指南.md)):
- Script reads from `config/course_items_mapping.csv`
- Dry-run mode (`d`) validates without database changes
- `media_file` stores folder paths: `resources/images/naming/001/`
- Random file selection at runtime via `app/utils/resource_utils.py`
- PlayResourceHandler emits `resolvedFile` field with actual file path
- Creates/updates "命名课程" (Naming) and "拟声课程" (Vocalization) courses

### Running the Application

**Backend (Flask + SocketIO)**:
```powershell
# Default: http://127.0.0.1:8080, reads config/analyzers.yaml
python app.py

# Force real mode (overrides YAML)
$env:USE_REAL_ANALYZERS="true"; python app.py

# Enable detailed logging to logs/
$env:LOG_LEVEL="DEBUG"; python app.py
```

**Frontend Options**:

1. **Legacy Child Page** (Static HTML + Vanilla JS):
   - Access via `http://127.0.0.1:8080/child`
   - Files: `templates/child.html`
   - Static assets: `static/js/child.js`
   - Direct Socket.IO connection without proxy

2. **Modern React Frontend** (Recommended for teacher interface):
   ```powershell
   cd teacher_frontend
   npm install       # First time only
   npm run dev       # Starts Vite dev server on http://localhost:5173
   ```
   - **Stack**: Vite + React + TypeScript + Tailwind CSS + Radix UI (shadcn/ui)
   - **Backend Communication**: REST API + Socket.IO via Vite proxy
   - **Hot Module Replacement**: Changes reflect instantly during development
   
   **Component Structure**:
   - `App.tsx`: Main router managing page state (login → studentInfo → courseSelection → control)
   - `components/LoginPage.tsx`: Teacher authentication (POST `/api/login`)
   - `components/StudentInfoPage.tsx`: Student selection (GET `/api/students`)
   - `components/CourseSelectionPage.tsx`: Course/item browser (GET `/courses`)
   - `components/ControlPage.tsx`: Live teaching panel with real-time feedback
   - `components/ui/`: Reusable shadcn/ui components (Button, Card, Dialog, etc.)
   
   **Socket.IO Client Pattern** (from ControlPage.tsx):
   ```typescript
   import { io, Socket } from 'socket.io-client';
   
   // Connect to backend via Vite proxy
   const socket = io('http://127.0.0.1:8080', {
     transports: ['websocket', 'polling']
   });
   
   // Join session room for targeted events
   socket.emit('join_session', { sessionId, role: 'teacher' });
   
   // Listen for analysis results
   socket.on('match_result', (data: MatchResult) => {
     console.log('Match score:', data.score);
   });
   
   // Trigger course playback + session creation
   socket.emit('play_resource', { 
     action: 'play', 
     studentId, 
     courseId, 
     itemId 
   });
   ```
   
   **Vite Proxy Configuration** (`vite.config.ts`):
   - `/api` → Flask backend (REST endpoints)
   - `/courses` → Flask backend (course data)
   - `/static` → Flask backend (media files)
   - `/socket.io` → Flask backend (WebSocket, `ws: true`)

### Testing Mode Switching
```python
from app.core.config import enable_real_analyzers, enable_mock_analyzers
from app.core.auto_register import auto_register

# In tests before service initialization:
enable_mock_analyzers()
auto_register()
analysis_service = get_analysis_service()
```

## Project-Specific Patterns

### Session State Transitions (Critical for Correctness)
```
CREATED → RECORDING → ANALYZING → COMPLETED/FAILED/CANCELLED
```
- **Must** call `session.start()` before recording starts
- **Must** call `manager.end_session(id)` for cleanup (releases threads/buffers)
- Check state via `session.state` property before operations
- Session data persists in `storage/recordings/{session_id}/`

### WebSocket Event Protocol (Bidirectional)

**Client → Server (inbound)**:
- `video_frame`: {data: base64, timestamp}
- `audio_chunk`: {data: numpy array buffer, sample_rate}
- `stop_recording`: {session_id}
- `play_resource`: {action: "play", studentId, courseId, itemId, aux} → creates session + triggers robot arm
- `join_session`: {sessionId, role: "teacher"/"child"} → joins Socket.IO room for targeted messaging
- `leave_session`: {sessionId} → leaves room

**Server → Teacher (outbound)**:
- `match_result`: {score, confidence, keypoints_matched}
- `attention_update`: {attention_score, sustained_duration}
- `session_summary`: {total_score, accuracy, attention_percentage}

**Server → Child (outbound)**:
- `trigger_action`: {action_type, audio_file} → auto-play praise

**WebSocket Handlers Pattern** (`app/sockets/handlers.py`):
- Event logic isolated in handler classes (e.g., `PlayResourceHandler`, `VideoFrameHandler`)
- Handlers return data for emit (don't emit directly—handled by event registration)
- Use `join_room(session_id)` for room-based broadcasting to teacher/child independently

### Analysis Context Flow (Must Be Passed Through Pipelines)
```python
AnalysisContext(
    session_id=str,        # Required: links to session
    course_type=str,       # Required: 'mimic'/'naming'/etc for type selection
    student_id=int,        # Optional: for student-specific matching rules
    attempt_number=int     # Optional: tracks multiple attempts
)
```
- Create once per session, pass through all pipeline calls
- Used by `TriggerFactory` for threshold selection
- Logged for debugging via `logger.info(f"Analysis {context}")`

**Course Type Mapping** (determines which analyzers to activate):
- `'mimic'`, `'imitation'`, `'pose'`: Activates pose analysis + pose matcher
- `'naming'`, `'speech'`: Activates speech analysis + speech matcher
- `'vocalization'`: Audio analysis
- `'matching'`, `'sequencing'`: Combined vision + attention analysis

### Trigger System (Conditional Actions)
- **Predefined**: `TriggerFactory.create_pose_match_trigger(threshold=0.85)`
- **Custom**: Inherit `BaseTrigger`, override `should_trigger(context, result) → bool`
- **Execution**: `ActionExecutor.set_socketio(socketio)` connects WebSocket emission
- **Result Flow**: Analyzer → Matcher → Trigger → Action → FeedbackService WebSocket push

### Pose Analysis Integration (MediaPipe)
- **Model path**: `models/pose_landmarker_lite.task` (auto-downloads on first run if missing)
- **Target setting**: `analysis_service.set_pose_target(session_id, keypoints_dict, name)`
  - Keypoints dict format: `{0: {x, y}, 1: {x, y}, ...}` (33 keypoints)
- **Normalization in RealPoseMatcher**: Hip center (23+24)/2 as origin, shoulder distance (12-11) as scale
  - Handles pose at any distance/rotation (translation+scale invariant)
  - Mock version uses simpler Euclidean distance

### Robot Arm Integration (E.I.Art Doll)
The robot arm control module (`app/robot/`) provides physical doll control via OSC protocol:
- **Access**: `/robot` page for control panel, `/api/robot/*` REST API, WebSocket `robot_*` events
- **OSC Communication**: `MotionPlayer` sends UDP messages to DollSer C++ controller (default: 127.0.0.1:12000)
- **Recording**: TensorFlow.js pose detection in browser → frames sent via WebSocket → saved to `doll/data/motions.json`
- **4-Level Mapping Priority**: Item > Student-Course > Course > Default (see `MappingResolver` in `app/robot/mapping_resolver.py`)
- **Integration**: `play_resource` event triggers `robot_service.trigger_course_event()` for synchronized robot action

**Robot WebSocket Events** (prefix `robot_`):
- `robot_pose_data`: Realtime pose from browser to hardware
- `robot_play_motion`, `robot_stop_playback`: Playback control
- `robot_start_recording`, `robot_stop_recording`: Recording control

### Audio System (Multi-Voice Playback)
The audio system (`app/audio/`) provides intelligent voice playback for child client feedback:
- **Configuration**: `config/audio_manifest.yaml` defines all audio entries with metadata (tags, strategies, cooling periods)
- **Selection Strategies**: Random, Sequential, Weighted, Context-aware (prevents short-term repetition)
- **Integration**: Teacher actions (question/praise/hint buttons) trigger via `play_resource` event with `aux` parameter
- **Room-Based Delivery**: WebSocket events target specific session rooms (`session_{id}_child`)

**Audio Module Architecture**:
```
AudioService → AudioSelector → AudioRegistry → audio_manifest.yaml
     ↓              ↓                ↓
AudioEmitter → Socket.IO → Child Client Player
```

**Key Components**:
- `AudioRegistry` (`app/audio/registry.py`): Loads YAML manifest, provides entry lookup by ID/tags
- `AudioSelector` (`app/audio/selector.py`): Selection logic with cooling mechanism, strategy execution
- `AudioService` (`app/audio/service.py`): High-level API processing `play_resource` events
- `AudioEmitter` (`app/audio/events.py`): WebSocket emission to child client
- `AudioController` (`app/audio/controller.py`): Queue management, playback control, status tracking

**Audio WebSocket Events** (child client):
- `play_audio`: {entryId, filePath, metadata} → triggers playback on child client
- `stop_audio`: {} → stops current playback
- `audio_status`: {status, entryId} → child reports playback state (playing/paused/ended/error)

**YAML Manifest Structure** (`config/audio_manifest.yaml`):
```yaml
entries:
  - id: "praise_001"
    title: "做得很棒"
    tags: ["praise", "encouragement"]
    files:
      - path: "static/resources/audios/praise/001.mp3"
        weight: 1.0
    metadata:
      duration: 2.5
      cooling_period: 10  # seconds before same entry can replay
    selection_strategy: "random"  # or 'sequential', 'weighted', 'context_aware'
```

**Usage Pattern** (from teacher action):
```typescript
// Teacher clicks "praise" button in ControlPage.tsx
socket.emit('play_resource', {
  action: 'play',
  studentId,
  courseId,
  itemId,
  aux: { praise: true }  // Triggers audio system
});

// Backend processes in PlayResourceHandler
// → AudioService.process_play_resource()
// → AudioSelector.select_by_tags(['praise'])
// → AudioEmitter.play_audio(session_id, entry, file)
// → Child client receives 'play_audio' event
```

**Common Audio System Tasks**:
- **Add new audio**: Update `config/audio_manifest.yaml` with entry ID, files, tags
- **Change strategy**: Set `selection_strategy` per entry (random/sequential/weighted)
- **Adjust cooling**: Modify `cooling_period` to control repetition timing
- **Debug playback**: Check logs for "AudioService", "AudioSelector" with `LOG_LEVEL=DEBUG`

## Testing Conventions
- **Integration tests**: `tests/test_*_integration.py` (use real MediaPipe if available)
- **Unit tests**: Run individually with `sys.path.insert(0, '...')` for standalone execution
- **Mock/Real toggle**: Call `enable_real_analyzers()` or `enable_mock_analyzers()` from `app.core.config` **before** `auto_register()`
- **Quick iteration**: Always test with mock mode first (no GPU needed), then validate with real mode
- **Frame counter reset**: Each analyzer has separate `_frame_counter` that resets on session start (affects sampling)

## Common Pitfalls

### ❌ DON'T
- Call `analyzer.analyze()` directly → **Always use `analyze_with_sampling()`** for automatic sampling control
- Forget `auto_register()` before initializing services → No analyzers registered, pipelines fail silently
- Mix frame indices across mock/real modes → Each mode maintains separate counters; affects sampling accuracy
- Hardcode file paths → Use `Config.get_video_file_path(session_id)` and `Config.get_audio_file_path(session_id)`
- Create analyzer/matcher directly → Always use registry: `AnalyzerRegistry.get_analyzer('pose')`
- Emit WebSocket events from within pipeline threads → Use `ActionExecutor` which queues to main thread
- Change analyzer mode mid-session → Mode must be set before session starts (before `auto_register()`)
- Access keypoint `'confidence'` directly → May not exist in Real/MediaPipe mode (uses `'visibility'` instead)

### ✅ DO
- Check `analyzer.is_ready` before calling (especially for Real/MediaPipe analyzers which need initialization)
- Call `manager.end_session(id)` in finally block to guarantee cleanup (releases queue threads)
- Pass `AnalysisContext` through all pipeline calls for traceability and logging
- Use `logger.info(f"...")` with context for debugging state transitions
- Test with Mock first (instant results), validate behavior, then switch to Real mode
- Store analysis results before emit via FeedbackService (for persistence)
- Always respect `WindowAnalysisScheduler` timing (Type B analyses run every 1 second)
- Handle both `visibility` (Real/MediaPipe) and `confidence` (Mock) fields in matchers using `kp.get('confidence', kp.get('visibility', 1.0))`

## File Organization Logic
- `app/core/`: Framework components (analyzers, pipelines, registry)
- `app/core/vision/` & `app/core/audio/`: Analyzer implementations
- `app/core/matchers/`: Comparison/matching logic
- `app/services/`: High-level orchestration (session, media, analysis, feedback)
- `app/audio/`: Voice playback system (registry, selector, service, events, controller)
- `app/robot/`: Robot arm control (recorder, player, mapping, OSC)
- `app/sockets/`: WebSocket event handlers (handlers.py, robot_events.py, audio_events.py)
- `config/`: YAML configs (analyzers.yaml.example, audio_manifest.yaml, course_items_mapping.csv)
- `doll/data/`: Robot motion data files (motions.json, course_map.json, students.json)
- `static/`: Frontend assets (child.html), static resources (recordings/, resources/)
- `templates/`: HTML templates served by Flask (child.html, server.html, robot/*)
- `teacher_frontend/`: Modern React frontend (Vite + Tailwind + Radix UI), separate dev server (port 5173)
  - `App.tsx`: Main app component with page state management
  - `components/`: Page components (LoginPage, StudentInfoPage, CourseSelectionPage, ControlPage)
  - `components/ui/`: Reusable shadcn/ui components
  - `src/`: Vite entry point (main.tsx)
  - `vite.config.ts`: Vite configuration with backend proxy
- `database/`: DB models, migration scripts, sample data generators

## Critical Dependencies
```
Flask + Flask-SocketIO: Web framework + WebSocket
SQLAlchemy: ORM for SQLite (database/models.py)
MediaPipe: Pose/face analysis (real analyzers only)
OpenCV + NumPy: Image processing
PyAudio: Audio capture (child client side)
PyYAML: Config file parsing
python-osc: OSC protocol for robot arm communication
```

## Platform-Specific Notes

### Windows Compatibility
- **Video codec**: Uses MJPG (`VIDEO_CODEC='mjpg'`) for better Windows compatibility
- **Resolution**: Frontend child.js configured for 640x480 (must match `VIDEO_WIDTH`/`VIDEO_HEIGHT` in config)
- **Audio**: 16000 Hz sample rate, mono channel (must match frontend settings)
- **Terminal commands**: Use PowerShell syntax (`;` for command chaining, NOT `&&`)
- **Environment variables**: Set with `$env:VAR_NAME="value"` in PowerShell
- **Path separators**: Use `Path()` from `pathlib` for cross-platform compatibility

### Cross-Platform File Paths
- Always use `Path()` from `pathlib` for path construction
- Config provides helper methods: `Config.get_video_file_path()`, `Config.get_audio_file_path()`
- Static files served from `static/` directory (recordings, resources, etc.)

## Debug Commands & Utilities

### Environment Checks
```bash
# Verify MediaPipe model is downloaded
ls models/pose_landmarker_lite.task

# Check analyzer config (YAML takes priority, then env vars)
cat config/analyzers.yaml  # Must exist (copy from .example if missing)

# Enable verbose logging
LOG_LEVEL=DEBUG python app.py  # Outputs to logs/app.log

# Check what analyzers/matchers registered
python -c "from app.core.auto_register import auto_register; auto_register(); from app.core.registry import AnalyzerRegistry; print(AnalyzerRegistry.list_analyzers())"
```

### Testing Individual Analyzers
```python
from app.core.config import enable_mock_analyzers
from app.core.auto_register import auto_register
from app.core.registry import AnalyzerRegistry
from app.core.models import AnalysisContext

enable_mock_analyzers()
auto_register()
analyzer = AnalyzerRegistry.get_analyzer('pose')
ctx = AnalysisContext(session_id='test', course_type='mimic')
result = analyzer.analyze_with_sampling(frame, ctx)
```

### Common Startup Issues
- **"No module named 'mediapipe'"**: Install via `pip install mediapipe` or run in Mock mode with `config/analyzers.yaml` set to `global.mode: mock`
- **"'confidence' KeyError" in pose_matcher**: Ensure matcher mode matches analyzer mode (both mock or both real). See [BUGFIX_confidence字段错误.md](BUGFIX_confidence字段错误.md)
- **WebSocket events not received**: Check `ActionExecutor` has `socketio` set via `ActionExecutor.set_socketio(socketio)` in `app.py`
- **Session not ending cleanly**: Always call `manager.end_session(id)` to stop internal threads; check logs for "Ending session" messages
- **Backend fails to start**: Ensure `config/analyzers.yaml` exists (copy from `analyzers.yaml.example`), check Python dependencies are installed
- **React frontend fails to start**: Run `npm install` first, ensure Node.js 16+ is installed, check for port conflicts on 5173
- **Socket.IO connection errors**: Verify backend is running on port 8080, check Vite proxy configuration in `vite.config.ts`

## Documentation References
- Architecture: [app/README.md](app/README.md), [项目结构说明.md](项目结构说明.md)
- Analyzer integration: [分析模型接入指南_V2.md](分析模型接入指南_V2.md)
- Database schema: [database/README.md](database/README.md)
- Known issues: [BUGFIX_confidence字段错误.md](BUGFIX_confidence字段错误.md), [BUGFIX_姿态匹配分数随机问题.md](BUGFIX_姿态匹配分数随机问题.md)
- Stage summaries: `阶段*完成总结.md` files (development history)

---

## Quick Reference: First-Time Setup

### 1. Install Dependencies
```powershell
# Backend Python packages
pip install -r requirements.txt

# Frontend Node packages (optional, for React UI)
cd teacher_frontend
npm install
cd ..
```

### 2. Create Configuration
```powershell
# Copy analyzer config (choose 'mock' mode for quick start)
copy config\analyzers.yaml.example config\analyzers.yaml
```

### 3. Initialize Database
```powershell
python database/init_db.py                    # Creates tables + admin account
python database/import_course_resources.py    # Import courses (use 'd' for dry-run first)
```

### 4. Download MediaPipe Model (Optional, for real mode)
```powershell
# Model auto-downloads on first run, or manually download:
# Place pose_landmarker_lite.task in models/ directory
```

### 5. Start Application
```powershell
# Backend (Terminal 1)
python app.py

# React Frontend (Terminal 2, optional)
cd teacher_frontend
npm run dev
```

### 6. Access Application
- Legacy UI: http://127.0.0.1:8080/
- React UI: http://localhost:5173/
- Default login: admin / admin123

---

## Quick Reference: Configuration Examples

### Enable Real Mode (MediaPipe)
```bash
# Option 1: Environment variable (highest priority)
USE_REAL_ANALYZERS=true python app.py

# Option 2: Edit config/analyzers.yaml
global:
  mode: real
```

### Enable Mock Mode (Fast Testing)
```bash
# Option 1: Environment variable
USE_REAL_ANALYZERS=false python app.py

# Option 2: Edit config/analyzers.yaml
global:
  mode: mock
```

### Per-Analyzer Override (YAML only)
```yaml
global:
  mode: mock  # Default
analyzers:
  pose:
    mode: real       # Override global for this analyzer
    sample_rate: 0.1 # Analyze 10% of frames
    min_detection_confidence: 0.7
```

**When debugging**: Check `logs/` directory (e.g., `logs/app.log`), enable `LOG_LEVEL=DEBUG` env var, inspect session state via `session_manager._sessions` dict in REPL.
