import { spawn } from "node:child_process";

export async function transcodeToWav16kMono(input: Buffer, mimeType: string): Promise<Buffer> {
  const normalizedMime = mimeType.toLowerCase();
  if (normalizedMime.includes("wav")) {
    return input;
  }
  return transcodeWithFfmpeg(input, normalizedMime.includes("webm") ? "webm" : normalizedMime.includes("ogg") ? "ogg" : undefined);
}

function transcodeWithFfmpeg(input: Buffer, inputFormat?: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const args = ["-hide_banner", "-loglevel", "error"];
    if (inputFormat) {
      args.push("-f", inputFormat);
    }
    args.push("-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1");

    const process = spawn("ffmpeg", args, { stdio: ["pipe", "pipe", "pipe"] });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    process.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    process.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    process.on("error", (error) => {
      reject(new Error(`FFMPEG_UNAVAILABLE:${error.message}`));
    });
    process.on("close", (code) => {
      const output = Buffer.concat(stdout);
      if (code === 0 && output.byteLength > 44) {
        resolve(output);
        return;
      }
      const detail = Buffer.concat(stderr).toString("utf8").trim();
      reject(new Error(detail ? `FFMPEG_TRANSCODE_FAILED:${detail}` : "FFMPEG_TRANSCODE_FAILED"));
    });
    process.stdin.write(input);
    process.stdin.end();
  });
}
