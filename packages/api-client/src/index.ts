import type { RenderJobApi, ConversationThreadApi, ConversationMessageApi, MemoryItemApi } from '@graphytion/contracts';

export type MediaGenerationApi = {
  id: string;
  project_id: string;
  media_type: 'image' | 'video';
  provider_key: string;
  model_key: string;
  status: 'queued' | 'processing' | 'cancel_requested' | 'completed' | 'failed' | 'cancelled';
  provider_operation_id?: string | null;
  provider_operation_status?: 'not_started' | 'submitted' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled' | 'unknown';
  error_code?: string | null;
  attempt_count: number;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
  last_error?: string | null;
  last_error_class?: string | null;
  quota_reconciliation_status?: 'pending' | 'complete' | 'reversed' | 'not_required' | 'failed';
  estimated_provider_cost_microusd?: number | null;
  operational_cost_microusd?: number | null;
  quota_debit_microusd?: number | null;
  economics_status?: 'complete' | 'partial' | 'unpriced';
  billing_mode?: 'free_personal';
  generation_config?: Record<string, unknown>;
  provider_provenance?: Record<string, unknown>;
  provider_usage?: Record<string, unknown> | null;
  provider_cost_status?: 'priced' | 'unpriced';
  provider_cost_microusd?: number | null;
  created_at?: string;
  completed_at?: string | null;
  artifact?: {
    id: string;
    file_name: string;
    content_type: string;
    size_bytes: number;
    sha256: string;
    signed_url: string;
  } | null;
};

export type MediaGenerationCreate = {
  media_type: 'image' | 'video';
  provider_key?: 'gemini';
  model_key: string;
  prompt: string;
  generation_config?: Record<string, unknown>;
};

export type RenderCreateRequestApi = {
  snapshot: unknown;
  render_profile_id?: string | null;
  composition_version?: string;
};

export type RenderCreateResponseApi = {
  data: { render_job_id: string; status: string; timeline_hash?: string; replayed?: boolean };
};

export type RenderCancelResponseApi = {
  data: { render_job_id: string; status: string };
};

export type RenderDownloadResponseApi = {
  data: { signed_url: string; expires_in: number };
};

export type ApiClientOptions = {
  baseUrl: string;
  fetcher?: typeof fetch;
};

export class ApiClientError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiClientError';
  }
}

function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)graphytion\.csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function ensureCsrf(baseUrl: string, fetcher: typeof fetch): Promise<string | null> {
  let token = readCsrfCookie();
  if (token) return token;
  const csrfUrl = new URL('csrf', baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`);
  await fetcher(csrfUrl, { method: 'GET', credentials: 'include', cache: 'no-store' });
  token = readCsrfCookie();
  return token;
}

export function createApiClient(options: ApiClientOptions) {
  const fetcher = options.fetcher ?? fetch;

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (typeof init.body === 'string' && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    const method = (init.method ?? 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && typeof document !== 'undefined') {
      const csrf = await ensureCsrf(options.baseUrl, fetcher);
      if (csrf) headers.set('X-CSRF-Token', csrf);
    }
    // Browser clients authenticate only through the same-origin HttpOnly-cookie BFF.
    // Never accept or forward a JavaScript-readable bearer token.
    headers.delete('Authorization');
    if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', crypto.randomUUID());
    const url = new URL(
      path.replace(/^\//, ''),
      options.baseUrl.endsWith('/') ? options.baseUrl : `${options.baseUrl}/`,
    );
    const response = await fetcher(url, {
      ...init,
      method,
      headers,
      credentials: init.credentials ?? 'include',
      cache: 'no-store',
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        body && typeof body === 'object' && 'error' in body
          ? (body as { error: { code?: string; message?: string; request_id?: string } }).error
          : undefined;
      const nested = body && typeof body === 'object' && 'detail' in body
        ? (body as { detail?: { message?: string } | string }).detail
        : undefined;
      const message =
        detail?.message ??
        (typeof nested === 'string' ? nested : nested?.message) ??
        'API request failed';
      throw new ApiClientError(
        response.status,
        detail?.code ?? 'HTTP_ERROR',
        message,
        detail?.request_id,
      );
    }
    return body as T;
  }

  return {
    request,
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown, key?: string) =>
      request<T>(path, {
        method: 'POST',
        body: JSON.stringify(body),
        headers: key ? { 'Idempotency-Key': key } : undefined,
      }),
    put: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
    upload: <T>(path: string, body: FormData, key?: string) =>
      request<T>(path, {
        method: 'POST',
        body,
        headers: key ? { 'Idempotency-Key': key } : undefined,
      }),
    delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
    createMediaGeneration: (projectId: string, body: MediaGenerationCreate, key: string) =>
      request<{ data: { generation_id: string; status: string; replayed?: boolean } }>(
        `projects/${projectId}/media-generations`,
        { method: 'POST', body: JSON.stringify(body), headers: { 'Idempotency-Key': key } },
      ),
    listMediaGenerations: (projectId: string) =>
      request<{ data: MediaGenerationApi[] }>(`projects/${projectId}/media-generations`),
    getMediaGeneration: (id: string) =>
      request<{ data: MediaGenerationApi }>(`media-generations/${id}`),
    cancelMediaGeneration: (id: string) =>
      request<{ data: { generation_id: string; status: string } }>(`media-generations/${id}/cancel`, { method: 'POST' }),
    retryMediaGeneration: (id: string, key: string) =>
      request<{ data: { generation_id: string; status: string; replayed?: boolean; billing_mode?: 'free_personal' } }>(
        `media-generations/${id}/retry`,
        { method: 'POST', headers: { 'Idempotency-Key': key } },
      ),
    listRenders: (projectId: string) =>
      request<{ data: RenderJobApi[] }>(`projects/${projectId}/renders`),
    createRender: (projectId: string, body: RenderCreateRequestApi, key: string) =>
      request<RenderCreateResponseApi>(`projects/${projectId}/renders`, {
        method: 'POST', body: JSON.stringify(body), headers: { 'Idempotency-Key': key },
      }),
    cancelRender: (id: string) =>
      request<RenderCancelResponseApi>(`renders/${id}/cancel`, { method: 'POST' }),
    downloadRender: (id: string) =>
      request<RenderDownloadResponseApi>(`renders/${id}/download`),
    listConversations: (workspaceId: string) =>
      request<{ data: ConversationThreadApi[] }>(`workspaces/${workspaceId}/conversations`),
    createConversation: (workspaceId: string, body: { title?: string; project_id?: string | null; metadata?: Record<string, unknown> }) =>
      request<{ data: ConversationThreadApi }>(`workspaces/${workspaceId}/conversations`, { method: 'POST', body: JSON.stringify(body) }),
    listConversationMessages: (conversationId: string) =>
      request<{ data: ConversationMessageApi[] }>(`conversations/${conversationId}/messages`),
    addConversationMessage: (conversationId: string, body: { content: string; metadata?: Record<string, unknown> }) =>
      request<{ data: ConversationMessageApi }>(`conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify(body) }),
    listMemories: (workspaceId: string, params: { query?: string; project_id?: string; limit?: number } = {}) => {
      const query = new URLSearchParams();
      if (params.query) query.set('query', params.query);
      if (params.project_id) query.set('project_id', params.project_id);
      if (params.limit) query.set('limit', String(params.limit));
      return request<{ data: MemoryItemApi[] }>(`workspaces/${workspaceId}/memories?${query.toString()}`);
    },
    createMemory: (workspaceId: string, body: {
      scope: 'personal' | 'project'; memory_type: 'preference' | 'context' | 'fact' | 'decision' | 'episodic' | 'procedural';
      project_id?: string | null; title: string; content: string;
      source_type: 'conversation' | 'project' | 'user_input' | 'agent_output' | 'import';
      source_id?: string | null; provenance?: Record<string, unknown>; tags?: string[];
      importance?: number; confidence?: number; expires_at?: string | null;
    }) => request<{ data: MemoryItemApi }>(`workspaces/${workspaceId}/memories`, { method: 'POST', body: JSON.stringify(body) }),
    getProjectMemoryContext: (projectId: string, query = '', conversationId?: string) => {
      const params = new URLSearchParams();
      if (query) params.set('query', query);
      if (conversationId) params.set('conversation_id', conversationId);
      return request<{ data: { memory: MemoryItemApi[]; conversation: ConversationMessageApi[]; provenance: Array<Record<string, unknown>> } }>(
        `projects/${projectId}/memory-context?${params.toString()}`
      );
    },
    deleteMemory: (memoryId: string) => request<void>(`memories/${memoryId}`, { method: 'DELETE' }),
  };
}
