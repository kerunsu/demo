import type { TtsProvider } from "../types.js";

export class NoopTtsProvider implements TtsProvider {
  name = "none";

  async synthesize() {
    return null;
  }
}
