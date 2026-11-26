export type ApiClientOptions = {
  baseUrl: string;
  getAccessToken?: () => Promise<string | null>;
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
    const token = await options.getAccessToken?.();
    if (token) headers.set('Authorization', `Bearer ${token}`);
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
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  };
}
