/**
 * Preload bridge. The single, narrow, schema-validated API the
 * renderer sees. See ADR-0001.
 *
 * The renderer cannot reach node, the filesystem, the database, or
 * any other sidecar command except through the methods exposed here.
 * The set of methods here is the renderer-visible attack surface;
 * every method passes through to a typed request on the sidecar.
 */
import { contextBridge, ipcRenderer } from 'electron';
import type { Frame, ResponseFrame, EventFrame } from '../shared/ipc-schema.js';
import type { MethodName, ParamsOf, ResultOf } from '../shared/ipc-methods.js';

interface PendingRequest {
  readonly resolve: (value: unknown) => void;
  readonly reject: (reason: Error) => void;
}

const pending: Map<string, PendingRequest> = new Map();

ipcRenderer.on('sidecar:frame', (_event, frame: Frame) => {
  if (frame.kind === 'response' || frame.kind === 'error') {
    const waiter = pending.get(frame.id);
    if (!waiter) return;
    pending.delete(frame.id);
    if (frame.kind === 'error') {
      waiter.reject(new Error(frame.error.message));
    } else {
      waiter.resolve(frame.result);
    }
  }
  // Events are forwarded as a separate channel; the renderer
  // subscribes via `sidecarEvents`.
});

function invoke<M extends MethodName>(method: M, params: ParamsOf<M>): Promise<ResultOf<M>> {
  return ipcRenderer.invoke('sidecar:request', { method, params }) as Promise<ResultOf<M>>;
}

const api = {
  app: {
    getStatus: () => invoke('app.getStatus', {}),
    getCapabilities: () => invoke('app.getCapabilities', {}),
  },
  project: {
    list: () => invoke('project.list', {}),
    create: (params: ParamsOf<'project.create'>) => invoke('project.create', params),
    get: (projectId: string) => invoke('project.get', { projectId }),
    update: (params: ParamsOf<'project.update'>) => invoke('project.update', params),
    archive: (projectId: string) => invoke('project.archive', { id: projectId }),
  },
  source: {
    listVolumes: () => invoke('source.listVolumes', {}),
    inspect: (params: ParamsOf<'source.inspect'>) => invoke('source.inspect', params),
  },
  profile: {
    save: (params: ParamsOf<'profile.save'>) => invoke('profile.save', params),
    list: () => invoke('profile.list', {}),
    get: (id: number) => invoke('profile.get', { id }),
  },
  asset: {
    list: (params?: ParamsOf<'asset.list'>) => invoke('asset.list', params ?? {}),
    get: (assetId: string) => invoke('asset.get', { assetId }),
  },
  replica: {
    verify: (params: ParamsOf<'replica.verify'>) => invoke('replica.verify', params),
    list: (assetId: string) => invoke('replica.list', { assetId }),
  },
  intake: {
    createSession: (params: ParamsOf<'intake.createSession'>) =>
      invoke('intake.createSession', params),
    addDestination: (params: ParamsOf<'intake.addDestination'>) =>
      invoke('intake.addDestination', params),
    evaluate: (sessionId: string) => invoke('intake.evaluate', { sessionId }),
  },
  job: {
    create: (params: ParamsOf<'job.create'>) => invoke('job.create', params),
    list: (projectId?: string) => invoke('job.list', projectId ? { projectId } : {}),
    get: (id: string) => invoke('job.get', { id }),
    transition: (params: ParamsOf<'job.transition'>) => invoke('job.transition', params),
    subscribe: (jobId: string) => invoke('job.subscribe', { jobId }),
    unsubscribe: (jobId: string) => invoke('job.unsubscribe', { jobId }),
  },
  audit: {
    list: (params?: ParamsOf<'audit.list'>) => invoke('audit.list', params ?? {}),
    backfill: () => invoke('audit.backfill', {}),
  },
  sidecarEvents: {
    onJobUpdated(handler: (event: EventFrame) => void): () => void {
      const listener = (_e: unknown, frame: EventFrame) => handler(frame);
      ipcRenderer.on('sidecar:event:job.updated', listener);
      return () => ipcRenderer.removeListener('sidecar:event:job.updated', listener);
    },
  },
};

export type MediaMateAPI = typeof api;

contextBridge.exposeInMainWorld('mediaMate', api);

// Type-only re-export so the renderer can `declare` the global.
export type { Frame, ResponseFrame, EventFrame };
