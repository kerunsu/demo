import type { CameraFrameAck, CameraFrameSampleDescriptor } from "child-education-training-demo/shared/behavior-frames";
import { FRONTEND_RUNTIME_CONFIG } from "../../config/runtime";

function behaviorUrl(path: string) {
  return `${FRONTEND_RUNTIME_CONFIG.apiBaseUrl}${path}`;
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  const body = (await response.json()) as { success: boolean; data: T; error?: { message: string } };
  if (!response.ok || !body.success) {
    throw new Error(body.error?.message ?? `Behavior frame request failed with ${response.status}`);
  }
  return body.data;
}

export async function sendCameraFrameDescriptor(input: CameraFrameSampleDescriptor): Promise<CameraFrameAck> {
  const response = await fetch(behaviorUrl(`/behavior/${input.sessionId}/camera/frames/${input.frameId}`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseApiResponse<CameraFrameAck>(response);
}
