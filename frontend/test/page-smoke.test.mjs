import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { test } from "node:test";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const distRoot = path.join(frontendRoot, "dist");
const appSourcePath = path.join(frontendRoot, "src", "App.tsx");
const stylesPath = path.join(frontendRoot, "src", "styles.css");
const courseFlowHookPath = path.join(frontendRoot, "src", "hooks", "useCourseFlow.ts");
const voiceCaptureHookPath = path.join(frontendRoot, "src", "hooks", "useVoiceCapture.ts");
const audioPlaybackPath = path.join(frontendRoot, "src", "features", "voice", "audioPlayback.ts");
const browserAudioCapturePath = path.join(frontendRoot, "src", "features", "voice", "browserAudioCapture.ts");
const mediaIngressClientPath = path.join(frontendRoot, "src", "features", "voice", "mediaIngressClient.ts");
const browserCameraCapturePath = path.join(frontendRoot, "src", "features", "camera", "browserCameraCapture.ts");
const cameraFrameClientPath = path.join(frontendRoot, "src", "features", "camera", "cameraFrameClient.ts");
const reportMetricsPath = path.join(frontendRoot, "src", "features", "report", "reportMetrics.ts");
const reportV2ContentPath = path.join(frontendRoot, "src", "features", "report", "ProfessionalReportV2Content.tsx");
const runtimeSourcePath = path.join(frontendRoot, "src", "config", "runtime.ts");
const pageShellsPath = path.join(frontendRoot, "src", "pages", "PageShells.tsx");
const robotScreenPath = path.join(frontendRoot, "src", "pages", "RobotScreen.tsx");
const serverDashboardPath = path.join(frontendRoot, "src", "pages", "ServerDashboard.tsx");
const monitorCameraPanelPath = path.join(frontendRoot, "src", "features", "monitor", "MonitorCameraPanel.tsx");
const useMonitorSessionPath = path.join(frontendRoot, "src", "hooks", "useMonitorSession.ts");
const typesSourcePath = path.join(frontendRoot, "src", "types", "index.ts");

async function readText(filePath) {
  return readFile(filePath, "utf8");
}

test("built app shell and primary page copy are present", async () => {
  const indexHtml = await readText(path.join(distRoot, "index.html"));
  assert.match(indexHtml, /<div id="root"><\/div>/);
  assert.match(indexHtml, /type="module"/);

  const assetFiles = await readdir(path.join(distRoot, "assets"));
  const jsFile = assetFiles.find((file) => file.endsWith(".js"));
  const cssFile = assetFiles.find((file) => file.endsWith(".css"));
  assert.ok(jsFile, "expected a bundled JavaScript asset");
  assert.ok(cssFile, "expected a bundled CSS asset");

  const bundle = await readText(path.join(distRoot, "assets", jsFile));
  for (const expectedText of ["home-btn-start", "course-card-fun", "report-detail-container", "robot-screen-pure", "server-dashboard"]) {
    assert.ok(bundle.includes(expectedText), `expected built bundle to include ${expectedText}`);
  }
});

test("App keeps welcome-to-course-selection startup path intact", async () => {
  const appSource = await readText(appSourcePath);
  const courseFlowSource = await readText(courseFlowHookPath);
  assert.ok(appSource.includes('useState<AppPage>("welcome")'), "default page should remain welcome");
  assert.ok(appSource.includes('setPage("select")'), "welcome page should still navigate to course selection");
  assert.ok(appSource.includes("handleStartTraining"), "course selection should still expose start training flow");
  assert.ok(courseFlowSource.includes('onPageChange("training")'), "start flow should still enter training page");
  assert.ok(courseFlowSource.includes('onPageChange("report")'), "completed training should still enter report page");
});

test("course state and actions live in the course flow hook", async () => {
  const appSource = await readText(appSourcePath);
  const courseFlowSource = await readText(courseFlowHookPath);

  assert.ok(appSource.includes("useCourseFlow"), "App should consume the course flow hook");
  for (const expectedBoundary of [
    "selectedCourses",
    "courseQueue",
    "handleStartTraining",
    "handleSelectAnswer",
    "mergeTrainingReports"
  ]) {
    assert.ok(courseFlowSource.includes(expectedBoundary), `course hook should own ${expectedBoundary}`);
  }
});

test("report derived metrics are isolated and wording stays educational", async () => {
  const appSource = await readText(appSourcePath);
  const reportMetricsSource = await readText(reportMetricsPath);
  const reportV2Source = await readText(reportV2ContentPath);
  const typesSource = await readText(typesSourcePath);

  assert.ok(appSource.includes("deriveReportMetrics"), "App should use report metric helpers");
  assert.ok(appSource.includes("ProfessionalReportV2Content"), "App should render the report V2 content component");
  assert.ok(reportMetricsSource.includes("demoReferenceIndex"), "report helpers should label demo-only comparison output");
  assert.ok(typesSource.includes("m6-expanded-report-v1"), "frontend report type should expose M6-C expanded report schema");
  assert.ok(typesSource.includes("containsRawChatText: false"), "expanded report export boundary should exclude raw child chat text");
  assert.ok(!reportV2Source.includes("超过同龄"), "report UI should not claim peer percentile ranking");
  assert.ok(!reportV2Source.includes("高于常模"), "report UI should not claim an unsupported norm comparison");
  assert.ok(reportV2Source.includes("深度诊断报告 / Deep Diagnosis"), "report V2 should expose diagnosis section with educational boundary");
  assert.ok(reportV2Source.includes("本报告仅供教育参考"), "report UI should keep the education-reference boundary");
});

test("voice capture and audio playback boundaries are isolated", async () => {
  const appSource = await readText(appSourcePath);
  const voiceHookSource = await readText(voiceCaptureHookPath);
  const audioPlaybackSource = await readText(audioPlaybackPath);
  const browserAudioSource = await readText(browserAudioCapturePath);
  const mediaIngressSource = await readText(mediaIngressClientPath);

  assert.ok(appSource.includes("useVoiceCapture"), "App should use the voice capture hook");
  assert.ok(voiceHookSource.includes("BrowserAudioCaptureController"), "voice hook should use MediaRecorder capture as the main path");
  assert.ok(voiceHookSource.includes("startMediaStream"), "voice hook should start backend media ingress");
  assert.ok(voiceHookSource.includes("sendMediaChunk"), "voice hook should send MediaRecorder chunks to the backend");
  assert.ok(voiceHookSource.includes("transcribeMediaStream"), "voice hook should trigger backend local STT");
  assert.ok(voiceHookSource.includes("BROWSER_SPEECH_COMPAT_FALLBACK"), "browser SpeechRecognition should be an explicit compatibility fallback");
  assert.ok(voiceHookSource.includes("voiceFallbackReason"), "voice hook should expose a microphone degradation reason");
  assert.ok(browserAudioSource.includes("getUserMedia"), "browser audio capture should own microphone permission requests");
  assert.ok(browserAudioSource.includes("MediaRecorder"), "browser audio capture should chunk raw microphone audio");
  assert.ok(browserAudioSource.includes("enumerateDevices"), "browser audio capture should support device selection and refresh");
  assert.ok(browserAudioSource.includes("devicechange"), "browser audio capture should react to microphone device changes");
  assert.ok(browserAudioSource.includes("onChunk"), "browser audio capture should expose chunk callbacks for M4 media ingress");
  assert.ok(browserAudioSource.includes("getByteTimeDomainData"), "browser audio capture should expose audio level metering");
  assert.ok(!browserAudioSource.includes("localStorage"), "browser audio capture must not persist raw audio locally");
  assert.ok(!browserAudioSource.includes("download"), "browser audio capture must not create raw audio downloads");
  assert.ok(mediaIngressSource.includes("MEDIA_CHUNK_CONTENT_TYPE"), "media ingress client should send binary chunks");
  assert.ok(mediaIngressSource.includes("FRONTEND_RUNTIME_CONFIG.apiBaseUrl"), "media ingress client should use runtime API config");
  assert.ok(mediaIngressSource.includes("chunk.blob"), "media ingress client should post captured blob chunks");
  assert.ok(mediaIngressSource.includes("transcribeMediaStream"), "media ingress client should expose STT transcription trigger");
  assert.ok(!mediaIngressSource.includes("FileReader"), "media ingress client must not convert raw audio to base64 JSON");
  assert.ok(appSource.includes("playChatReplyAudio"), "App should delegate audio playback");
  assert.ok(audioPlaybackSource.includes("audioBase64"), "audio helper should only play explicit chat reply audio");
});

test("camera capture boundary uses low-fps descriptors without local raw-frame persistence", async () => {
  const appSource = await readText(appSourcePath);
  const browserCameraSource = await readText(browserCameraCapturePath);
  const cameraClientSource = await readText(cameraFrameClientPath);

  assert.ok(browserCameraSource.includes("getUserMedia"), "browser camera capture should own camera permission requests");
  assert.ok(browserCameraSource.includes("videoinput"), "browser camera capture should enumerate video input devices");
  assert.ok(browserCameraSource.includes("sampleFps"), "browser camera capture should expose a low-fps sampling option");
  assert.ok(browserCameraSource.includes("Math.min(2"), "camera sampling should cap the default development frame rate");
  assert.ok(browserCameraSource.includes("rawFramePersisted: false"), "camera descriptors should explicitly forbid raw-frame persistence");
  assert.ok(browserCameraSource.includes("frameHash"), "camera descriptors should carry a frame hash instead of raw frame data");
  assert.ok(browserCameraSource.includes("visualFeatures"), "camera descriptors should carry local low-granularity visual features");
  assert.ok(browserCameraSource.includes("ATTENTION_ALGORITHM_V2"), "camera capture should use attention scoring v2");
  assert.ok(browserCameraSource.includes("attention-scoring"), "camera capture should share attention scoring with backend");
  assert.ok(browserCameraSource.includes("FaceDetector"), "camera capture should use local browser face detection when available");
  assert.ok(browserCameraSource.includes("detectFacesWithMediaPipe"), "camera capture should fall back to MediaPipe when FaceDetector is unavailable");
  assert.ok(browserCameraSource.includes("browser-mediapipe-face"), "camera capture should tag MediaPipe detections with a dedicated provider");
  assert.ok(!browserCameraSource.includes("localStorage"), "camera capture must not persist raw frames locally");
  assert.ok(!browserCameraSource.includes("download"), "camera capture must not create frame downloads");
  assert.ok(cameraClientSource.includes("/behavior/"), "camera frame client should send descriptors to the behavior API");
  assert.ok(cameraClientSource.includes("JSON.stringify(input)"), "camera frame client should send descriptor metadata, not binary frame payloads");
  assert.ok(appSource.includes("BrowserCameraCaptureController"), "child training page should wire camera capture into the main flow");
  assert.ok(appSource.includes("sendCameraFrameDescriptor"), "child training page should send camera descriptors during training");
  assert.ok(appSource.includes("CAMERA_FIRST_START_DELAY_MS"), "camera cold start should wait briefly so first question animations can render");
  assert.ok(appSource.includes("switchQuestion"), "question changes should rotate per-question video without restarting the camera");
  assert.ok(browserCameraSource.includes("switchQuestion"), "camera controller should keep the device open and split video per question");
  assert.ok(appSource.includes("camera-device-availability-v1"), "camera failures should be sent as data-quality descriptors");
});

test("child UI restores visible icons instead of fallback question marks", async () => {
  const appSource = await readText(appSourcePath);
  const reportV2Source = await readText(reportV2ContentPath);
  const styleSource = await readText(stylesPath);

  for (const expectedIcon of ["★", "🎤"]) {
    assert.ok(appSource.includes(expectedIcon), `expected App UI to include ${expectedIcon}`);
  }
  for (const expectedIcon of ["🧩", "🧠"]) {
    assert.ok(reportV2Source.includes(expectedIcon), `expected report V2 UI to include ${expectedIcon}`);
  }
  assert.match(styleSource, /\.badge-star\s*{[^}]*color:\s*#fbbf24;/s, "selected course badge star should render yellow");
  assert.equal(appSource.includes('<div className="badge-star">?</div>'), false);
  assert.equal(appSource.includes('<div className="stat-icon">??</div>'), false);
  assert.equal(appSource.includes("{voicePanelOpen ? \"?\" : \"+\"}"), false);
});

test("ordering rule text stays compact and success animation keeps its original pace", async () => {
  const styleSource = await readText(stylesPath);

  assert.match(styleSource, /\.rule-text\s*{[^}]*white-space:\s*nowrap;/s, "ordering rule text should remain on one line");
  assert.match(styleSource, /animation:\s*card-hop-flip-success 2s/s, "success animation should keep the original playback pace");
  assert.match(styleSource, /success-check-pop 0\.45s[^;]*1\.35s both/s, "success check mark timing should keep the original animation choreography");
});

test("frontend page shells define the current page boundaries", async () => {
  const appSource = await readText(appSourcePath);
  const pageShellsSource = await readText(pageShellsPath);

  for (const shellName of [
    "WelcomePageShell",
    "CourseSelectPageShell",
    "TrainingPageShell",
    "ReportPageShell",
    "ReportDetailPageShell"
  ]) {
    assert.ok(appSource.includes(shellName), `App should render through ${shellName}`);
    assert.ok(pageShellsSource.includes(`function ${shellName}`), `PageShells should export ${shellName}`);
  }
});

test("frontend exposes child, robot, and server screen entry shells", async () => {
  const appSource = await readText(appSourcePath);
  const runtimeSource = await readText(runtimeSourcePath);
  const robotSource = await readText(robotScreenPath);
  const serverSource = await readText(serverDashboardPath);
  const monitorCameraSource = await readText(monitorCameraPanelPath);
  const monitorSessionSource = await readText(useMonitorSessionPath);
  const styleSource = await readText(stylesPath);

  assert.ok(runtimeSource.includes('child: "/child"'), "runtime config should define the child route");
  assert.ok(runtimeSource.includes('robot: "/robot"'), "runtime config should define the robot route");
  assert.ok(runtimeSource.includes('server: "/server"'), "runtime config should define the server route");
  assert.ok(appSource.includes("getScreenRoleFromPathname"), "App should choose a screen role from the current path");
  assert.ok(appSource.includes("<RobotScreen />"), "App should render the robot screen shell for /robot");
  assert.ok(appSource.includes("<ServerDashboard />"), "App should render the server dashboard shell for /server");
  assert.ok(robotSource.includes("RobotGifStage"), "robot screen should crossfade GIF layers without flashing");
  assert.equal(robotSource.includes("robot-status-panel"), false, "robot screen should not render engineering status UI");
  assert.ok(robotSource.includes("connectRealtime"), "robot screen should connect to the realtime event channel");
  assert.ok(robotSource.includes("ACTIVE_SESSION_STORAGE_KEY"), "robot screen should follow the child screen's active session");
  assert.ok(robotSource.includes("resolveRobotScreenSessionId"), "robot screen should resolve the active backend session");
  assert.ok(robotSource.includes("setInterval(syncSessionId"), "robot screen should attach when /robot opens before training starts");
  assert.ok(robotSource.includes("SNAPSHOT_POLL_INTERVAL_MS"), "robot screen should poll snapshots as a fallback for missed websocket events");
  assert.ok(robotSource.includes("getSessionSnapshot(sessionId, lastSnapshotEventIdRef.current)"), "robot screen should consume incremental animation events");
  assert.match(styleSource, /\.robot-gif-fullscreen\s*{[^}]*width:\s*100vw;[^}]*height:\s*100vh;[^}]*object-fit:\s*fill;/s);
  assert.ok(serverSource.includes("实时干预监控与分析控制台"), "server dashboard should expose engineering monitor UI");
  assert.ok(serverSource.includes("MonitorCameraPanel"), "server dashboard should render the camera monitor panel");
  assert.ok(serverSource.includes("useMonitorSession"), "server dashboard should use websocket-aware monitor hook");
  assert.ok(monitorSessionSource.includes('screenRole: "operator"'), "monitor session hook should use operator websocket role");
  assert.ok(serverSource.includes("MonitorAttentionChart"), "server dashboard should render attention trend chart");
  assert.ok(monitorCameraSource.includes("browser-attention-v2"), "camera monitor panel should label live attention provider");
  assert.ok(serverSource.includes("MonitorVoicePipeline"), "server dashboard should render grouped voice pipeline");
  assert.ok(serverSource.includes("rawMediaPersistence"), "server dashboard should show raw media persistence state");
});
test("frontend runtime config exposes LAN API and WebSocket settings", async () => {
  const runtimeSource = await readText(runtimeSourcePath);
  const apiSource = await readText(path.join(frontendRoot, "src", "services", "api.ts"));
  const realtimeSource = await readText(path.join(frontendRoot, "src", "services", "realtimeClient.ts"));

  assert.ok(runtimeSource.includes("VITE_API_BASE_URL"), "runtime config should read API base URL");
  assert.ok(runtimeSource.includes("VITE_WS_URL"), "runtime config should read WebSocket URL");
  assert.ok(apiSource.includes("FRONTEND_RUNTIME_CONFIG.apiBaseUrl"), "API client should use runtime API base URL");
  assert.ok(realtimeSource.includes("FRONTEND_RUNTIME_CONFIG.wsUrl"), "realtime client should use runtime WebSocket URL");
});

test("robot screen has GIF adapter and mock speech ACK boundaries", async () => {
  const adapterSource = await readText(path.join(frontendRoot, "src", "features", "robot", "gifAnimationAdapter.ts"));
  const robotSource = await readText(robotScreenPath);
  const speechSource = await readText(path.join(frontendRoot, "src", "features", "robot", "mockSpeechPlayback.ts"));
  const realSpeechSource = await readText(path.join(frontendRoot, "src", "features", "robot", "speechPlayback.ts"));
  const voiceTurnClientSource = await readText(path.join(frontendRoot, "src", "features", "voice", "voiceTurnClient.ts"));
  const ackSource = await readText(path.join(frontendRoot, "src", "services", "eventAck.ts"));

  assert.ok(adapterSource.includes("class GifAnimationAdapter"), "robot screen should have a GIF adapter");
  assert.ok(adapterSource.includes("ignore_if_playing"), "GIF adapter should honor ignore_if_playing interrupt policy");
  assert.ok(adapterSource.includes("isIdleLoop"), "GIF adapter should distinguish idle loop from feedback playback");
  assert.ok(speechSource.includes("playMockSpeech"), "robot screen should use mock local speech playback");
  assert.ok(realSpeechSource.includes("new Audio"), "robot screen should be able to play synthesized TTS audio");
  assert.ok(realSpeechSource.includes("data:${input.mimeType};base64"), "robot speech playback should consume explicit audio payloads");
  assert.ok(voiceTurnClientSource.includes("/voice-turns/"), "robot screen should request backend TTS synthesis");
  assert.ok(robotSource.includes("processedSpeechTurns"), "robot screen should deduplicate speech turns");
  assert.ok(robotSource.includes("pendingSpeechEvent"), "robot screen should defer speech until browser sound is enabled");
  assert.ok(robotSource.includes("stopSpeechPlayback"), "robot screen should stop active playback during cleanup or replacement");
  assert.ok(robotSource.includes("requestRobotSpeech"), "robot screen should request synthesized speech for feedback");
  assert.ok(ackSource.includes("createAckDomainEvent"), "ACKs should be available as WebSocket domain events");
});
