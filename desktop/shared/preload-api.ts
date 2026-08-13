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
  job: {
    subscribe: (jobId: string) => invoke('job.subscribe', { jobId }),
    unsubscribe: (jobId: string) => invoke('job.unsubscribe', { jobId }),
  },
  sidecarEvents: {
    onJobUpdated(_handler: (event: EventFrame) => void): () => void {
      return () => undefined;
    },
  },
};

export type MediaMateAPI = typeof api;
