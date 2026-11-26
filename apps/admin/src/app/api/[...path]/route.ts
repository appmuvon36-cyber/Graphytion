import { NextRequest } from 'next/server';
import { handleSessionProxy } from '@/lib/session-proxy';

export const runtime = 'nodejs';
type Context = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Context) {
  const { path } = await context.params;
  return handleSessionProxy(request, path);
}
export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const HEAD = handle;
