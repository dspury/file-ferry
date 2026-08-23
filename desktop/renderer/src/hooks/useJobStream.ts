/**
 * Live job state from the sidecar's `job.updated` events.
 *
 * Activity used to be a snapshot taken when the screen mounted: a running
 * transfer sat at whatever percentage it happened to be at, and only a
 * cancel/retry (which reloads) ever moved it. That is the wrong behaviour
 * for a tool whose main job is watching bytes land.
 *
 * The sidecar only emits for jobs the renderer has subscribed to, so this
 * subscribes to every non-finished job in the list and drops the
 * subscription when the job finishes or the screen unmounts.
 */
import { useEffect, useRef, useState } from 'react';
import { isJobUpdatedParams } from '../../../shared/replay.js';
import { mergeJobSnapshot, streamableJobIds } from '../lib/activity.js';
import type { JobDetail, JobSnapshot } from '../../../shared/ipc-methods.js';

export interface JobStream {
  /** Latest snapshot per job id, for the jobs that have emitted one. */
  readonly snapshots: ReadonlyMap<string, JobSnapshot>;
  /** How many jobs currently hold a live subscription. */
  readonly subscribed: number;
}

export function useJobStream(jobs: readonly JobDetail[], onUnknownJob: () => void): JobStream {
  const [snapshots, setSnapshots] = useState<ReadonlyMap<string, JobSnapshot>>(new Map());

  // The listener is attached once, so it must not close over `jobs`. These
  // refs let it see the current list without being torn down and rebuilt on
  // every render — which would drop events landing in the gap.
  const knownIds = useRef<ReadonlySet<string>>(new Set());
  const unknownHandler = useRef(onUnknownJob);
  knownIds.current = new Set(jobs.map((job) => job.id));
  unknownHandler.current = onUnknownJob;

  useEffect(() => {
    return window.ferry.sidecarEvents.onJobUpdated((frame) => {
      // The frame comes off the wire, so its params are checked rather than
      // assumed — the same guard Electron main records the snapshot with.
      if (!isJobUpdatedParams(frame.params)) return;
      const snapshot = frame.params.snapshot;
      if (!knownIds.current.has(snapshot.id)) {
        // A job created elsewhere (the Offload screen, another window, or a
        // recovery sweep) cannot be rendered from a snapshot alone: it has
        // no command or project. Ask for a fresh list instead of inventing
        // a half-populated row.
        unknownHandler.current();
        return;
      }
      setSnapshots((prev) => {
        const previous = prev.get(snapshot.id);
        // Stale events are dropped here as well as in `mergeJobSnapshot`,
        // so the map itself never regresses and React skips the re-render.
        if (previous !== undefined && snapshot.updatedAt < previous.updatedAt) return prev;
        const next = new Map(prev);
        next.set(snapshot.id, snapshot);
        return next;
      });
    });
  }, []);

  // Subscriptions follow the set of live job ids, computed from the *merged*
  // rows. Using the raw list would keep a subscription (and the "watched"
  // count) alive for a job that finished via an event, because `job.list`
  // still remembers it as running until something reloads it.
  const streamable = streamableJobIds(
    jobs.map((job) => mergeJobSnapshot(job, snapshots.get(job.id) ?? null)),
  );
  // The key is a string so a new-but-equal array from a re-render does not
  // tear down and rebuild every subscription.
  const streamKey = streamable.join(',');

  useEffect(() => {
    const ids = streamKey === '' ? [] : streamKey.split(',');
    for (const id of ids) {
      // A failed subscribe is not worth surfacing: the screen still shows
      // the state `job.list` returned, just without live updates.
      void window.ferry.job.subscribe(id).catch(() => undefined);
    }
    return () => {
      for (const id of ids) {
        void window.ferry.job.unsubscribe(id).catch(() => undefined);
      }
    };
  }, [streamKey]);

  return { snapshots, subscribed: streamable.length };
}
