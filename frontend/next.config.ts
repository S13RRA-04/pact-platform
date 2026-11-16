import type { NextConfig } from "next";
const apiOrigin = process.env.PACT_API_ORIGIN ?? "http://127.0.0.1:8000";
const config: NextConfig = {allowedDevOrigins:["127.0.0.1"],async rewrites(){return [{source:"/api/:path*",destination:`${apiOrigin}/api/:path*`}];}};
export default config;
