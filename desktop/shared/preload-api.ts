/**
 * The renderer-facing API surface. The implementation lives in
 * `electron/preload.ts`; this module re-exports the type so the
 * renderer can `declare global` against it without depending on
 * the electron code (which is outside the renderer's rootDir).
 */
import type { EventFrame } from './ipc-schema.js';
import type { MethodName, ParamsOf, ResultOf } from './ipc-methods.js';

function invoke<M extends MethodName>(_method: M, _params: ParamsOf<M>): Promise<ResultOf<M>> {
  return Promise.resolve(undefined as unknown as ResultOf<M>);
}

export const api = {
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
    onJobUpdated(_handler: (event: EventFrame) => void): () => void {
      return () => undefined;
    },
  },
};

export type MediaMateAPI = typeof api;
