import fs from "node:fs/promises";
import path from "node:path";
import type {
  RawMediaDiagnostics,
  RawMediaRuntimeConfig,
  SessionMediaAudioTurnRecord,
  SessionMediaConsentRecord,
  SessionMediaManifest,
  SessionMediaSummary,
  SessionMediaVideoStreamRecord
} from "child-education-training-demo/shared/raw-media";
import { RAW_MEDIA_MANIFEST_SCHEMA_VERSION } from "child-education-training-demo/shared/raw-media";
import { resolveProjectRoot } from "../app.js";
import { runtimeConfig } from "../config/runtime.js";

const SESSION_ID_PATTERN = /^sess_[a-z0-9]+$/i;
const manifestLocks = new Map<string, Promise<unknown>>();

function nowIso() {
  return new Date().toISOString();
}

function isValidSessionId(sessionId: string) {
  return SESSION_ID_PATTERN.test(sessionId);
}

function assertSessionId(sessionId: string) {
  if (!isValidSessionId(sessionId)) {
    throw new Error("Invalid sessionId");
  }
}

function resolveMediaRoot() {
  const projectRoot = resolveProjectRoot();
  const configured = runtimeConfig.rawMediaRoot;
  return path.isAbsolute(configured) ? configured : path.join(projectRoot, configured);
}

function sessionDirectory(sessionId: string) {
  assertSessionId(sessionId);
  return path.join(resolveMediaRoot(), sessionId);
}

function manifestFilePath(sessionId: string) {
  return path.join(sessionDirectory(sessionId), "manifest.json");
}

function manifestTempFilePath(sessionId: string) {
  return path.join(sessionDirectory(sessionId), "manifest.json.tmp");
}

function withManifestLock<T>(sessionId: string, task: () => Promise<T>) {
  const previous = manifestLocks.get(sessionId) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(task);
  manifestLocks.set(sessionId, next);
  return next;
}

function parseManifestJson(raw: string): { manifest: SessionMediaManifest; repaired: boolean } {
  const trimmed = raw.trim();
  try {
    return { manifest: JSON.parse(trimmed) as SessionMediaManifest, repaired: false };
  } catch {
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let index = 0; index < trimmed.length; index += 1) {
      const char = trimmed[index];
      if (inString) {
        if (escape) {
          escape = false;
          continue;
        }
        if (char === "\\") {
          escape = true;
          continue;
        }
        if (char === '"') inString = false;
        continue;
      }
      if (char === '"') {
        inString = true;
        continue;
      }
      if (char === "{") depth += 1;
      if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          const slice = trimmed.slice(0, index + 1);
          return {
            manifest: JSON.parse(slice) as SessionMediaManifest,
            repaired: index + 1 < trimmed.length
          };
        }
      }
    }
    throw new Error("Invalid manifest JSON");
  }
}

function chunkFileName(prefix: "chunk" | "segment", sequence: number, extension: string) {
  return `${prefix}-${String(sequence).padStart(4, "0")}.${extension}`;
}

function extensionForMimeType(mimeType: string, fallback: string) {
  if (mimeType.includes("jpeg") || mimeType.includes("jpg")) return "jpg";
  if (mimeType.includes("webp")) return "webp";
  if (mimeType.includes("webm")) return "webm";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("wav")) return "wav";
  return fallback;
}

function createEmptyManifest(sessionId: string): SessionMediaManifest {
  const timestamp = nowIso();
  return {
    schemaVersion: RAW_MEDIA_MANIFEST_SCHEMA_VERSION,
    sessionId,
    createdAt: timestamp,
    updatedAt: timestamp,
    audio: {},
    video: {}
  };
}

async function ensureSessionDirectory(sessionId: string) {
  await fs.mkdir(sessionDirectory(sessionId), { recursive: true });
}

async function readManifestFromDisk(sessionId: string): Promise<SessionMediaManifest | null> {
  if (!isValidSessionId(sessionId)) return null;
  try {
    const raw = await fs.readFile(manifestFilePath(sessionId), "utf8");
    return parseManifestJson(raw).manifest;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function readManifest(sessionId: string): Promise<SessionMediaManifest | null> {
  if (!isValidSessionId(sessionId)) return null;
  try {
    const raw = await fs.readFile(manifestFilePath(sessionId), "utf8");
    const parsed = parseManifestJson(raw);
    if (parsed.repaired) {
      await withManifestLock(sessionId, async () => {
        await writeManifestAtomic(parsed.manifest);
      });
    }
    return parsed.manifest;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function writeManifestAtomic(manifest: SessionMediaManifest) {
  manifest.updatedAt = nowIso();
  await ensureSessionDirectory(manifest.sessionId);
  const target = manifestFilePath(manifest.sessionId);
  const temp = manifestTempFilePath(manifest.sessionId);
  const body = `${JSON.stringify(manifest, null, 2)}\n`;

  let lastError: unknown;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await fs.writeFile(temp, body, "utf8");
    try {
      await fs.rename(temp, target);
      return;
    } catch (error) {
      lastError = error;
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "EPERM" || code === "EACCES" || code === "EBUSY" || code === "EEXIST") {
        try {
          await fs.rm(target, { force: true });
          await fs.rename(temp, target);
          return;
        } catch (retryError) {
          lastError = retryError;
          await delay(25 * (attempt + 1));
        }
        continue;
      }
      throw error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Failed to write manifest");
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function updateManifest(
  sessionId: string,
  updater: (manifest: SessionMediaManifest) => void
): Promise<SessionMediaManifest> {
  return withManifestLock(sessionId, async () => {
    const manifest = (await readManifestFromDisk(sessionId)) ?? createEmptyManifest(sessionId);
    updater(manifest);
    await writeManifestAtomic(manifest);
    return manifest;
  });
}

export function getRawMediaRuntimeConfig(): RawMediaRuntimeConfig {
  return {
    persistence: runtimeConfig.rawMediaPersistence,
    root: runtimeConfig.rawMediaRoot,
    retentionDays: runtimeConfig.rawMediaRetentionDays,
    requireConsent: runtimeConfig.rawMediaRequireConsent,
    encryption: runtimeConfig.rawMediaEncryption
  };
}

export function isRawMediaPersistenceEnabled() {
  return runtimeConfig.rawMediaPersistence === "enabled";
}

export async function hasSessionMediaConsent(sessionId: string) {
  const manifest = await readManifest(sessionId);
  return Boolean(manifest?.consent);
}

export async function canPersistSessionMedia(sessionId: string) {
  if (!isRawMediaPersistenceEnabled()) return false;
  if (!runtimeConfig.rawMediaRequireConsent) return true;
  return hasSessionMediaConsent(sessionId);
}

export async function recordSessionMediaConsent(
  sessionId: string,
  input: Omit<SessionMediaConsentRecord, "scope"> & { scope?: SessionMediaConsentRecord["scope"] }
) {
  assertSessionId(sessionId);
  if (!isRawMediaPersistenceEnabled()) {
    throw new Error("RAW_MEDIA_PERSISTENCE_DISABLED");
  }
  return updateManifest(sessionId, (manifest) => {
    manifest.consent = {
      recordedAt: input.recordedAt,
      scope: input.scope ?? "raw_audio_video",
      consentedBy: input.consentedBy
    };
  });
}

export async function getSessionMediaManifest(sessionId: string) {
  return readManifest(sessionId);
}

function sumManifestBytes(manifest: SessionMediaManifest) {
  let total = 0;
  for (const turn of Object.values(manifest.audio)) {
    total += turn.receivedBytes;
  }
  for (const stream of Object.values(manifest.video)) {
    total += stream.receivedBytes;
  }
  return total;
}

export async function getSessionMediaSummary(sessionId: string): Promise<SessionMediaSummary | null> {
  const manifest = await readManifest(sessionId);
  if (!manifest) return null;
  const missingChunkCount =
    Object.values(manifest.audio).reduce((sum, turn) => sum + turn.missingSequences.length, 0) +
    Object.values(manifest.video).reduce((sum, stream) => sum + stream.missingSequences.length, 0);
  return {
    sessionId: manifest.sessionId,
    consentRecorded: Boolean(manifest.consent),
    audioTurnCount: Object.keys(manifest.audio).length,
    videoStreamCount: Object.keys(manifest.video).length,
    totalPersistedBytes: sumManifestBytes(manifest),
    missingChunkCount,
    updatedAt: manifest.updatedAt
  };
}

export async function ensureAudioTurnRecord(input: {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  startedAt: string;
}) {
  const manifest = await updateManifest(input.sessionId, (manifest) => {
    const existing = manifest.audio[input.turnId];
    if (existing) return;
    manifest.audio[input.turnId] = {
      streamId: input.streamId,
      turnId: input.turnId,
      correlationId: input.correlationId,
      status: "started",
      startedAt: input.startedAt,
      chunks: [],
      missingSequences: [],
      receivedBytes: 0
    };
  });
  return manifest.audio[input.turnId]!;
}

export async function persistAudioChunk(input: {
  sessionId: string;
  streamId: string;
  turnId: string;
  correlationId: string;
  sequence: number;
  capturedAt: string;
  chunk: Buffer;
  mimeType: string;
  missingSequences: number[];
}) {
  if (!(await canPersistSessionMedia(input.sessionId))) {
    return { persisted: false as const, relativePath: undefined };
  }
  const extension = extensionForMimeType(input.mimeType, "webm");
  const relativePath = path.posix.join("audio", input.turnId, chunkFileName("chunk", input.sequence, extension));
  const absolutePath = path.join(sessionDirectory(input.sessionId), relativePath);
  await fs.mkdir(path.dirname(absolutePath), { recursive: true });
  await fs.writeFile(absolutePath, input.chunk);

  await updateManifest(input.sessionId, (manifest) => {
    const turn =
      manifest.audio[input.turnId] ??
      ({
        streamId: input.streamId,
        turnId: input.turnId,
        correlationId: input.correlationId,
        status: "receiving",
        startedAt: input.capturedAt,
        chunks: [],
        missingSequences: [],
        receivedBytes: 0
      } satisfies SessionMediaAudioTurnRecord);
    turn.status = "receiving";
    turn.chunks = turn.chunks.filter((item) => item.sequence !== input.sequence);
    turn.chunks.push({
      sequence: input.sequence,
      relativePath: relativePath.replace(/\\/g, "/"),
      byteLength: input.chunk.byteLength,
      capturedAt: input.capturedAt
    });
    turn.chunks.sort((left, right) => left.sequence - right.sequence);
    turn.missingSequences = [...input.missingSequences];
    turn.receivedBytes = turn.chunks.reduce((sum, item) => sum + item.byteLength, 0);
    manifest.audio[input.turnId] = turn;
  });
  return { persisted: true as const, relativePath };
}

export async function persistAudioMerged(input: {
  sessionId: string;
  turnId: string;
  chunks: Buffer[];
}) {
  if (!(await canPersistSessionMedia(input.sessionId))) {
    return { persisted: false as const, relativePath: undefined };
  }
  if (input.chunks.length === 0) {
    return { persisted: false as const, relativePath: undefined };
  }
  const relativePath = path.posix.join("audio", input.turnId, "merged.webm");
  const absolutePath = path.join(sessionDirectory(input.sessionId), relativePath);
  await fs.mkdir(path.dirname(absolutePath), { recursive: true });
  await fs.writeFile(absolutePath, Buffer.concat(input.chunks));

  await updateManifest(input.sessionId, (manifest) => {
    const turn = manifest.audio[input.turnId];
    if (!turn) return;
    turn.mergedRelativePath = relativePath;
    turn.status = turn.status === "cancelled" ? "cancelled" : "finished";
  });
  return { persisted: true as const, relativePath };
}

export async function ensureVideoStreamRecord(input: {
  sessionId: string;
  streamId: string;
  correlationId: string;
  questionId?: string;
  startedAt: string;
}) {
  const manifest = await updateManifest(input.sessionId, (manifest) => {
    const existing = manifest.video[input.streamId];
    if (existing) return;
    manifest.video[input.streamId] = {
      streamId: input.streamId,
      correlationId: input.correlationId,
      questionId: input.questionId,
      status: "started",
      startedAt: input.startedAt,
      segments: [],
      missingSequences: [],
      receivedBytes: 0
    };
  });
  return manifest.video[input.streamId]!;
}

export async function persistVideoSegment(input: {
  sessionId: string;
  streamId: string;
  correlationId: string;
  questionId?: string;
  sequence: number;
  capturedAt: string;
  segment: Buffer;
  mimeType: string;
  missingSequences: number[];
}) {
  if (!(await canPersistSessionMedia(input.sessionId))) {
    return { persisted: false as const, relativePath: undefined };
  }
  const extension = extensionForMimeType(input.mimeType, "webm");
  const relativePath = path.posix.join("video", input.streamId, chunkFileName("segment", input.sequence, extension));
  const absolutePath = path.join(sessionDirectory(input.sessionId), relativePath);
  await fs.mkdir(path.dirname(absolutePath), { recursive: true });
  await fs.writeFile(absolutePath, input.segment);

  await updateManifest(input.sessionId, (manifest) => {
    const stream =
      manifest.video[input.streamId] ??
      ({
        streamId: input.streamId,
        correlationId: input.correlationId,
        questionId: input.questionId,
        status: "receiving",
        startedAt: input.capturedAt,
        segments: [],
        missingSequences: [],
        receivedBytes: 0
      } satisfies SessionMediaVideoStreamRecord);
    stream.status = "receiving";
    stream.segments = stream.segments.filter((item) => item.sequence !== input.sequence);
    stream.segments.push({
      sequence: input.sequence,
      relativePath: relativePath.replace(/\\/g, "/"),
      byteLength: input.segment.byteLength,
      capturedAt: input.capturedAt
    });
    stream.segments.sort((left, right) => left.sequence - right.sequence);
    stream.missingSequences = [...input.missingSequences];
    stream.receivedBytes = stream.segments.reduce((sum, item) => sum + item.byteLength, 0);
    manifest.video[input.streamId] = stream;
  });
  return { persisted: true as const, relativePath };
}

export async function persistVideoThumbnail(input: {
  sessionId: string;
  streamId: string;
  thumbnail: Buffer;
  mimeType: string;
}) {
  if (!(await canPersistSessionMedia(input.sessionId))) {
    return { persisted: false as const, relativePath: undefined };
  }
  const extension = extensionForMimeType(input.mimeType, "jpg");
  const relativePath = path.posix.join("video", input.streamId, `thumbnail.${extension}`);
  const absolutePath = path.join(sessionDirectory(input.sessionId), relativePath);
  await fs.mkdir(path.dirname(absolutePath), { recursive: true });
  await fs.writeFile(absolutePath, input.thumbnail);

  await updateManifest(input.sessionId, (manifest) => {
    const stream = manifest.video[input.streamId];
    if (!stream) return;
    stream.thumbnailRelativePath = relativePath;
  });
  return { persisted: true as const, relativePath };
}

export async function finalizeAudioTurn(input: {
  sessionId: string;
  turnId: string;
  status: SessionMediaAudioTurnRecord["status"];
  endedAt: string;
}) {
  if (!isValidSessionId(input.sessionId)) return;
  await updateManifest(input.sessionId, (manifest) => {
    const turn = manifest.audio[input.turnId];
    if (!turn) return;
    turn.status = input.status;
    turn.endedAt = input.endedAt;
  });
}

export async function persistVideoMerged(input: {
  sessionId: string;
  streamId: string;
  segments: Buffer[];
}) {
  if (!(await canPersistSessionMedia(input.sessionId))) {
    return { persisted: false as const, relativePath: undefined };
  }
  if (input.segments.length === 0) {
    return { persisted: false as const, relativePath: undefined };
  }
  const relativePath = path.posix.join("video", input.streamId, "merged.webm");
  const absolutePath = path.join(sessionDirectory(input.sessionId), relativePath);
  await fs.mkdir(path.dirname(absolutePath), { recursive: true });
  await fs.writeFile(absolutePath, Buffer.concat(input.segments));

  await updateManifest(input.sessionId, (manifest) => {
    const stream = manifest.video[input.streamId];
    if (!stream) return;
    stream.mergedRelativePath = relativePath;
    stream.status = stream.status === "cancelled" ? "cancelled" : "finished";
  });
  return { persisted: true as const, relativePath };
}

export async function finalizeVideoStream(input: {
  sessionId: string;
  streamId: string;
  status: SessionMediaVideoStreamRecord["status"];
  endedAt: string;
}) {
  if (!isValidSessionId(input.sessionId)) return;
  await updateManifest(input.sessionId, (manifest) => {
    const stream = manifest.video[input.streamId];
    if (!stream) return;
    stream.status = input.status;
    stream.endedAt = input.endedAt;
  });
}

export async function deleteSessionMedia(sessionId: string) {
  assertSessionId(sessionId);
  await fs.rm(sessionDirectory(sessionId), { recursive: true, force: true });
}

async function listSessionDirectories() {
  const root = resolveMediaRoot();
  try {
    const entries = await fs.readdir(root, { withFileTypes: true });
    return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export async function purgeExpiredSessionMedia(referenceDate = new Date()) {
  if (!isRawMediaPersistenceEnabled()) {
    return { deletedSessionIds: [] as string[], retentionDays: runtimeConfig.rawMediaRetentionDays };
  }
  const retentionMs = runtimeConfig.rawMediaRetentionDays * 24 * 60 * 60 * 1000;
  const deletedSessionIds: string[] = [];
  for (const sessionId of await listSessionDirectories()) {
    if (!SESSION_ID_PATTERN.test(sessionId)) continue;
    const manifest = await readManifest(sessionId);
    const anchor = manifest?.updatedAt ?? manifest?.createdAt;
    if (!anchor) continue;
    if (referenceDate.getTime() - new Date(anchor).getTime() <= retentionMs) continue;
    await deleteSessionMedia(sessionId);
    deletedSessionIds.push(sessionId);
  }
  return { deletedSessionIds, retentionDays: runtimeConfig.rawMediaRetentionDays };
}

export async function getRawMediaDiagnostics(): Promise<RawMediaDiagnostics> {
  const rootPath = resolveMediaRoot();
  let rootExists = false;
  let rootWritable = false;
  try {
    await fs.access(rootPath);
    rootExists = true;
    await fs.access(rootPath, fs.constants.W_OK);
    rootWritable = true;
  } catch {
    rootExists = false;
    rootWritable = false;
  }

  let sessionCount = 0;
  let totalPersistedBytes = 0;
  if (rootExists) {
    for (const sessionId of await listSessionDirectories()) {
      if (!SESSION_ID_PATTERN.test(sessionId)) continue;
      const summary = await getSessionMediaSummary(sessionId);
      if (!summary) continue;
      sessionCount += 1;
      totalPersistedBytes += summary.totalPersistedBytes;
    }
  }

  return {
    persistence: runtimeConfig.rawMediaPersistence,
    rootPath,
    rootExists,
    rootWritable,
    retentionDays: runtimeConfig.rawMediaRetentionDays,
    requireConsent: runtimeConfig.rawMediaRequireConsent,
    sessionCount,
    totalPersistedBytes
  };
}

export async function resetRawMediaPersistenceForTests() {
  manifestLocks.clear();
  await fs.rm(resolveMediaRoot(), { recursive: true, force: true });
}
