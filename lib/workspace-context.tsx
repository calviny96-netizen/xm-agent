'use client';

import { createContext, useCallback, useContext, type ReactNode } from 'react';

const WorkspaceContext = createContext<string | undefined>(undefined);

export function WorkspaceProvider({ userId, children }: { userId: string; children: ReactNode }) {
  return <WorkspaceContext.Provider value={userId}>{children}</WorkspaceContext.Provider>;
}

/** The owner is captured per mounted workspace, never in a global mutable header. */
export function useWorkspaceFetch() {
  const userId = useContext(WorkspaceContext);
  return useCallback((path: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    if (userId) headers.set('X-XM-User-Id', userId);
    return fetch(`/api${path}`, { ...init, headers });
  }, [userId]);
}
