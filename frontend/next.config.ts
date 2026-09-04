import type { NextConfig } from 'next';

const backendOrigin = process.env.BACKEND_API_ORIGIN ?? 'http://127.0.0.1:8000';

const nextConfig: NextConfig = {
  experimental: {},
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
