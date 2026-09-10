import type { NextConfig } from 'next';

const backendOrigin = process.env.BACKEND_API_ORIGIN
  ?? (process.env.NODE_ENV === 'production'
    ? 'https://digi7-zsp-backend.onrender.com'
    : 'http://127.0.0.1:8000');

const nextConfig: NextConfig = {
  experimental: {},
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'same-origin' },
          { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*/',
        destination: `${backendOrigin}/api/:path*/`,
      },
      {
        source: '/api/:path*',
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
