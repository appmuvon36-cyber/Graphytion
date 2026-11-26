import { NextRequest } from 'next/server';
import { handleAuthCallback } from '@/lib/session-proxy';

export const runtime = 'nodejs';
export async function GET(request: NextRequest) {
  return handleAuthCallback(request);
}
