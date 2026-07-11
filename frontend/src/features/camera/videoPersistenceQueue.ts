type Task = () => Promise<void>;

/**
 * Serializes raw video persistence calls so finish never races ahead of segment uploads.
 */
export class VideoPersistenceQueue {
  private tail: Promise<void> = Promise.resolve();
  private streamSegmentTails = new Map<string, Promise<void>>();

  enqueue(task: Task) {
    const run = this.tail.then(task);
    this.tail = run.catch(() => undefined);
    return run;
  }

  enqueueSegment(streamId: string, task: Task) {
    const previous = this.streamSegmentTails.get(streamId) ?? Promise.resolve();
    const run = previous.then(task);
    this.streamSegmentTails.set(streamId, run.catch(() => undefined));
    return this.enqueue(task);
  }

  finishStream(streamId: string, task: Task) {
    const afterSegments = this.streamSegmentTails.get(streamId) ?? Promise.resolve();
    const run = afterSegments.then(task);
    this.streamSegmentTails.delete(streamId);
    this.tail = this.tail.then(() => run.catch(() => undefined));
    return run;
  }
}

export function isStaleVideoIngressError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return /VIDEO_STREAM_CLOSED|VIDEO_STREAM_NOT_STARTED|VIDEO_SEGMENT/i.test(message);
}
