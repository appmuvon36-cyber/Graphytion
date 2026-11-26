import type { NextConfig } from 'next';
const config: NextConfig = { poweredByHeader: false, reactStrictMode: true, transpilePackages: ['@graphytion/api-client', '@graphytion/contracts', '@graphytion/design-system'] };
export default config;
