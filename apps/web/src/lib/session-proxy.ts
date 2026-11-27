import { randomBytes, timingSafeEqual } from 'node:crypto';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

type TokenPayload = {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: { id?: string; email?: string };
};

const production = process.env.NODE_ENV === 'production';
const accessCookie = production ? '__Host-graphytion-access' : 'graphytion.access';
const refreshCookie = production ? '__Host-graphytion-refresh' : 'graphytion.refresh';
const csrfCookie = 'graphytion.csrf';

function config() {
  const apiBase = process.env.GRAPHYTION_API_URL?.replace(/\/$/, '');
  const appUrl = process.env.APP_PUBLIC_URL;
  const bffSecret = process.env.GRAPHYTION_BFF_SHARED_SECRET;
  if (!apiBase || !appUrl || !bffSecret) {
    throw new Error('BFF runtime requires GRAPHYTION_API_URL, APP_PUBLIC_URL and GRAPHYTION_BFF_SHARED_SECRET');
  }
  const apiUrl = new URL(apiBase);
  const origin = new URL(appUrl).origin;
  const privateRailwayApi =
    apiUrl.protocol === 'http:' && apiUrl.hostname.endsWith('.railway.internal');
  if (
    production &&
    (!origin.startsWith('https://') || (!apiUrl.origin.startsWith('https://') && !privateRailwayApi))
  ) {
    throw new Error('APP_PUBLIC_URL must use HTTPS; GRAPHYTION_API_URL must use HTTPS or Railway private networking');
  }
  if (bffSecret.length < 32) {
    throw new Error('GRAPHYTION_BFF_SHARED_SECRET must contain at least 32 characters');
  }
  return { apiBase, origin, bffSecret };
}

function csrfMatches(request: NextRequest): boolean {
  const cookie = request.cookies.get(csrfCookie)?.value ?? '';
  const header = request.headers.get('x-csrf-token') ?? '';
  if (!cookie || !header || cookie.length !== header.length) return false;
  return timingSafeEqual(Buffer.from(cookie), Buffer.from(header));
}

function checkOrigin(request: NextRequest): boolean {
  try {
    const expected = config().origin;
    const origin = request.headers.get('origin');
    if (origin) return origin === expected;
    const referer = request.headers.get('referer');
    return Boolean(referer && new URL(referer).origin === expected);
  } catch {
    return false;
  }
}

function ensureCsrf(response: NextResponse, request: NextRequest) {
  if (!request.cookies.get(csrfCookie)?.value) {
    response.cookies.set(csrfCookie, randomBytes(32).toString('hex'), {
      httpOnly: false,
      secure: production,
      sameSite: 'strict',
      path: '/',
      maxAge: 60 * 60 * 12,
    });
  }
}

function setSessionCookies(response: NextResponse, tokens: TokenPayload) {
  if (!tokens.access_token || !tokens.refresh_token) return;
  response.cookies.set(accessCookie, tokens.access_token, {
    httpOnly: true,
    secure: production,
    sameSite: 'lax',
    path: '/',
    maxAge: Math.max(60, Math.min(Number(tokens.expires_in ?? 3600), 3600)),
  });
  response.cookies.set(refreshCookie, tokens.refresh_token, {
    httpOnly: true,
    secure: production,
    sameSite: 'lax',
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
}

function clearSessionCookies(response: NextResponse) {
  for (const name of [accessCookie, refreshCookie]) {
    response.cookies.set(name, '', {
      httpOnly: true,
      secure: production,
      sameSite: 'lax',
      path: '/',
      maxAge: 0,
    });
  }
}

async function upstream(
  path: string,
  init: RequestInit = {},
  accessToken?: string,
  includeBffSecret = false,
): Promise<Response> {
  const { apiBase, bffSecret } = config();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (includeBffSecret) headers.set('X-Graphytion-BFF-Secret', bffSecret);
  return fetch(`${apiBase}/${path.replace(/^\//, '')}`, {
    ...init,
    headers,
    cache: 'no-store',
    redirect: 'manual',
  });
}

async function refreshTokens(request: NextRequest): Promise<TokenPayload | null> {
  const refreshToken = request.cookies.get(refreshCookie)?.value;
  if (!refreshToken) return null;
  const response = await upstream(
    '/auth/refresh',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Graphytion-Client-IP': request.headers.get('x-real-ip')
          ?? request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
          ?? 'unknown',
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    },
    undefined,
    true,
  );
  if (!response.ok) {
    // A transient Auth/API outage must never be interpreted as a revoked
    // session. Preserve the refresh cookie and let the browser retry.
    if (response.status >= 500) {
      throw new Error(`Supabase Auth refresh temporarily unavailable (HTTP ${response.status})`);
    }
    return null;
  }
  return (await response.json()) as TokenPayload;
}

function safeAuthResponse(tokens: TokenPayload, statusCode: number) {
  const user = tokens.user?.id
    ? { id: tokens.user.id, ...(tokens.user.email ? { email: tokens.user.email } : {}) }
    : null;
  return NextResponse.json(
    { authenticated: Boolean(tokens.access_token && tokens.refresh_token), user },
    { status: statusCode, headers: { 'Cache-Control': 'no-store' } },
  );
}

export async function handleSessionProxy(
  request: NextRequest,
  pathSegments: string[],
): Promise<NextResponse> {
  const path = pathSegments.join('/');
  const method = request.method.toUpperCase();
  const safeMethod = ['GET', 'HEAD', 'OPTIONS'].includes(method);

  if (path === 'csrf' && method === 'GET') {
    const response = NextResponse.json({ ok: true }, { headers: { 'Cache-Control': 'no-store' } });
    ensureCsrf(response, request);
    return response;
  }

  if (!safeMethod && (!checkOrigin(request) || !csrfMatches(request))) {
    return NextResponse.json({ error: { message: 'CSRF validation failed' } }, { status: 403 });
  }

  const accessToken = request.cookies.get(accessCookie)?.value;
  const authPath = path.startsWith('auth/');
  const body = safeMethod ? undefined : await request.arrayBuffer();
  const contentType = request.headers.get('content-type') ?? 'application/json';
  const forwardedHeaders = new Headers();
  forwardedHeaders.set('Content-Type', contentType);
  for (const name of ['accept', 'idempotency-key', 'x-request-id']) {
    const value = request.headers.get(name);
    if (value) forwardedHeaders.set(name, value);
  }
  // The API trusts this client address only when the accompanying BFF secret is valid.
  forwardedHeaders.set(
    'X-Graphytion-Client-IP',
    request.headers.get('x-real-ip')
      ?? request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
      ?? 'unknown',
  );
  forwardedHeaders.set('X-Graphytion-BFF-Secret', config().bffSecret);

  if (path === 'auth/session' && method === 'GET') {
    let response = accessToken ? await upstream('/me', { method: 'GET' }, accessToken) : null;
    let tokens: TokenPayload | null = null;
    if (!response || response.status === 401) {
      tokens = await refreshTokens(request);
      response = tokens?.access_token
        ? await upstream('/me', { method: 'GET' }, tokens.access_token)
        : null;
    }
    if (response && response.status >= 500) {
      return NextResponse.json(
        { error: { message: 'Session verification is temporarily unavailable. Retry without signing out.' } },
        { status: 503, headers: { 'Cache-Control': 'no-store', 'Retry-After': '5' } },
      );
    }
    const result = NextResponse.json(
      { authenticated: Boolean(response?.ok) },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
    if (tokens) setSessionCookies(result, tokens);
    // Clear cookies only after a definitive invalid/expired session response.
    if (!response?.ok) clearSessionCookies(result);
    ensureCsrf(result, request);
    return result;
  }

  if (path === 'auth/logout' && method === 'POST') {
    let token = accessToken;
    if (token) {
      const revoked = await upstream(
        '/auth/logout',
        {
          method: 'POST',
          headers: {
            'X-Graphytion-Client-IP': request.headers.get('x-real-ip')
              ?? request.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
              ?? 'unknown',
            'X-Graphytion-BFF-Secret': config().bffSecret,
          },
        },
        token,
      );
      if (!revoked.ok) token = undefined;
    }
    if (!token) {
      const rotated = await refreshTokens(request);
      if (rotated?.access_token) {
        await upstream('/auth/logout', { method: 'POST' }, rotated.access_token);
      }
    }
    const result = new NextResponse(null, { status: 204, headers: { 'Cache-Control': 'no-store' } });
    clearSessionCookies(result);
    ensureCsrf(result, request);
    return result;
  }

  if (['auth/login', 'auth/signup', 'auth/verify'].includes(path) && method === 'POST') {
    const response = await upstream(path, { method, headers: forwardedHeaders, body }, undefined, true);
    const payload = (await response.json().catch(() => ({}))) as TokenPayload & Record<string, unknown>;
    if (!response.ok) {
      const failed = NextResponse.json(payload, { status: response.status, headers: { 'Cache-Control': 'no-store' } });
      ensureCsrf(failed, request);
      return failed;
    }
    const safe = safeAuthResponse(payload, response.status);
    if (payload.access_token && payload.refresh_token) setSessionCookies(safe, payload);
    ensureCsrf(safe, request);
    return safe;
  }

  if (path === 'auth/refresh' && method === 'POST') {
    const tokens = await refreshTokens(request);
    if (!tokens?.access_token || !tokens.refresh_token) {
      const failed = NextResponse.json(
        { error: { message: 'Session expired. Please sign in again.' } },
        { status: 401, headers: { 'Cache-Control': 'no-store' } },
      );
      clearSessionCookies(failed);
      ensureCsrf(failed, request);
      return failed;
    }
    const result = safeAuthResponse(tokens, 200);
    setSessionCookies(result, tokens);
    ensureCsrf(result, request);
    return result;
  }

  let response = await upstream(
    path + request.nextUrl.search,
    { method, headers: forwardedHeaders, body },
    accessToken,
  );
  let rotatedTokens: TokenPayload | null = null;
  if (response.status === 401 && accessToken && !authPath) {
    rotatedTokens = await refreshTokens(request);
    if (rotatedTokens?.access_token) {
      response = await upstream(
        path + request.nextUrl.search,
        { method, headers: forwardedHeaders, body },
        rotatedTokens.access_token,
      );
    }
  }

  const bytes = ['HEAD'].includes(method) || [204, 304].includes(response.status)
    ? null
    : await response.arrayBuffer();
  const headers = new Headers();
  const responseType = response.headers.get('content-type');
  if (responseType) headers.set('Content-Type', responseType);
  headers.set('Cache-Control', 'no-store');
  const result = new NextResponse(bytes, { status: response.status, headers });
  if (rotatedTokens) setSessionCookies(result, rotatedTokens);
  if (response.status === 401) clearSessionCookies(result);
  ensureCsrf(result, request);
  return result;
}

export async function handleAuthCallback(request: NextRequest): Promise<NextResponse> {
  const tokenHash = request.nextUrl.searchParams.get('token_hash');
  const type = request.nextUrl.searchParams.get('type') ?? 'signup';
  const recovery = type === 'recovery';
  if (!tokenHash) {
    const result = NextResponse.redirect(new URL('/?auth_error=missing_token', request.nextUrl.origin));
    result.headers.set('Cache-Control', 'no-store');
    result.headers.set('Referrer-Policy', 'no-referrer');
    return result;
  }
  const response = await upstream(
    '/auth/verify',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token_hash: tokenHash, type }),
    },
    undefined,
    true,
  );
  if (!response.ok) {
    const result = NextResponse.redirect(new URL('/?auth_error=verification_failed', request.nextUrl.origin));
    result.headers.set('Cache-Control', 'no-store');
    result.headers.set('Referrer-Policy', 'no-referrer');
    return result;
  }
  const tokens = (await response.json()) as TokenPayload;
  const target = new URL('/', request.nextUrl.origin);
  if (recovery) target.searchParams.set('recovery', '1');
  const result = NextResponse.redirect(target);
  result.headers.set('Cache-Control', 'no-store');
  result.headers.set('Referrer-Policy', 'no-referrer');
  if (tokens.access_token && tokens.refresh_token) setSessionCookies(result, tokens);
  ensureCsrf(result, request);
  return result;
}
