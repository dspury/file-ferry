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
import type { PickRequest, PickResult } from '../shared/dialog.js';

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
    doctor: () => invoke('app.doctor', {}),
    openDiagnosticFolder: () =>
      ipcRenderer.invoke('app:openDiagnosticFolder') as Promise<{ logDir: string }>,
    diagnostics: () => ipcRenderer.invoke('app:diagnostics') as Promise<{ summary: string }>,
  },
  dialog: {
    pick: (request: PickRequest) =>
      ipcRenderer.invoke('dialog:pick', request) as Promise<PickResult>,
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
    preview: (params: ParamsOf<'profile.preview'>) => invoke('profile.preview', params),
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
    adoptSource: (params: ParamsOf<'intake.adoptSource'>) => invoke('intake.adoptSource', params),
  },
  job: {
    create: (params: ParamsOf<'job.create'>) => invoke('job.create', params),
    list: (projectId?: string) => invoke('job.list', projectId ? { projectId } : {}),
    get: (id: string) => invoke('job.get', { id }),
    transition: (params: ParamsOf<'job.transition'>) => invoke('job.transition', params),
    cancel: (id: string) => invoke('job.cancel', { id }),
    recover: () => invoke('job.recover', {}),
    resume: (id: string) => invoke('job.resume', { id }),
    retry: (id: string) => invoke('job.retry', { id }),
    subscribe: (jobId: string) => invoke('job.subscribe', { jobId }),
    unsubscribe: (jobId: string) => invoke('job.unsubscribe', { jobId }),
  },
  plan: {
    build: (params: ParamsOf<'plan.build'>) => invoke('plan.build', params),
  },
  receipt: {
    export: (params: ParamsOf<'receipt.export'>) => invoke('receipt.export', params),
    get: (operationId: string) => invoke('receipt.get', { operationId }),
  },
  settings: {
    get: () => invoke('settings.get', {}),
    update: (params: ParamsOf<'settings.update'>) => invoke('settings.update', params),
  },
  reconcile: {
    asset: (params: ParamsOf<'reconcile.asset'>) => invoke('reconcile.asset', params),
    project: (params: ParamsOf<'reconcile.project'>) => invoke('reconcile.project', params),
    acceptChange: (params: ParamsOf<'reconcile.acceptChange'>) =>
      invoke('reconcile.acceptChange', params),
  },
  organize: {
    preview: (params: ParamsOf<'organize.preview'>) => invoke('organize.preview', params),
    apply: (params: ParamsOf<'organize.apply'>) => invoke('organize.apply', params),
  },
  clips: {
    detect: (sourceId: number) => invoke('clips.detect', { sourceId }),
    list: (sourceId: number) => invoke('clips.list', { sourceId }),
  },
  derivatives: {
    list: (assetId: string) => invoke('derivatives.list', { assetId }),
  },
  manifest: {
    export: (projectId: string) => invoke('manifest.export', { projectId }),
    handoff: (projectId: string) => invoke('manifest.handoff', { projectId }),
    resolve: (projectId: string) => invoke('manifest.resolve', { projectId }),
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
