/** @type {import('next').NextConfig} */
const nextConfig = {
  // Data calls go through app/api/* route handlers (the API key stays server-side).
  // The UI loads no images from the API: it is deliberately free of party and organisation branding.
  reactStrictMode: true,
  async redirects() {
    // Landing page = the all-parties Insights view; the single-party booth dashboard is at /booths.
    return [{ source: "/", destination: "/insights", permanent: false }];
  },
};
export default nextConfig;
