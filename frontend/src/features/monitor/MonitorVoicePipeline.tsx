import type { MonitorSnapshot } from "../../services/monitorService";

type Props = {
  snapshot: MonitorSnapshot | null;
};

const PIPELINE_GROUPS = [
  { id: "capture", label: "监听与语音检测", stages: ["audio_capture_start", "first_audio_chunk", "vad_speech_start", "vad_speech_end"] },
  { id: "stt", label: "本地语音识别", stages: ["stt_request_start", "stt_complete", "transcript_available"] },
  { id: "reply", label: "回复生成", stages: ["chat_reply_generated"] },
  { id: "safety", label: "儿童安全审核", stages: ["safety_review"] },
  { id: "tts", label: "本地语音合成与播放", stages: ["tts_request_start", "tts_audio_ready", "robot_playback_start", "robot_playback_complete"] }
] as const;

function groupStatus(stages: readonly string[], pipeline: MonitorSnapshot["voice"]["currentPipeline"]) {
  const matched = pipeline.filter((step) => stages.includes(step.stage));
  if (matched.some((step) => step.status === "failed")) return "error";
  if (matched.some((step) => step.status === "running")) return "active";
  if (matched.length > 0 && matched.every((step) => step.status === "done")) return "done";
  if (matched.some((step) => step.status === "degraded")) return "active";
  return "pending";
}

function groupLatency(stages: readonly string[], pipeline: MonitorSnapshot["voice"]["currentPipeline"]) {
  return pipeline
    .filter((step) => stages.includes(step.stage) && typeof step.latencyMs === "number")
    .reduce((sum, step) => sum + (step.latencyMs ?? 0), 0);
}

function groupDetail(stages: readonly string[], pipeline: MonitorSnapshot["voice"]["currentPipeline"]) {
  const matched = pipeline.filter((step) => stages.includes(step.stage));
  const providers = [...new Set(matched.map((step) => step.provider).filter(Boolean))];
  const last = matched.length > 0 ? matched[matched.length - 1] : undefined;
  if (!last) return "等待语音回合";
  if (last.textPreview) return last.textPreview;
  return `${last.provider ?? "local/mock"} · ${last.status}`;
}

export function MonitorVoicePipeline({ snapshot }: Props) {
  const pipeline = snapshot?.voice.currentPipeline ?? [];
  return (
    <div className="server-pipeline-steps">
      {PIPELINE_GROUPS.map((group) => {
        const status = groupStatus(group.stages, pipeline);
        const latency = groupLatency(group.stages, pipeline);
        return (
          <div key={group.id} className={`server-pipeline-step ${status}`}>
            <div className="server-pipeline-dot">{status === "done" ? "✓" : status === "active" ? "··" : "·"}</div>
            <div className="server-pipeline-main">
              <strong>{group.label}</strong>
              <span>{groupDetail(group.stages, pipeline)}</span>
            </div>
            <div className="server-pipeline-time">{latency > 0 ? `${latency} ms` : "—"}</div>
          </div>
        );
      })}
    </div>
  );
}
