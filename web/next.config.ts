import path from "node:path";
import type { NextConfig } from "next";

// design-system은 web/ 외부(저장소 루트)에 있으므로 Turbopack workspace root를 한 단계 위로 확장.
// outputFileTracingRoot도 동일 — standalone 빌드 시 외부 파일 트레이싱 허용.
const REPO_ROOT = path.resolve(__dirname, "..");

const config: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: REPO_ROOT,
  turbopack: {
    root: REPO_ROOT,
  },

  // dev 환경에서 FastAPI로 바로 프록시. 프로덕션은 nginx가 처리하므로 영향 없음.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    const apiTarget = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
    return [
      { source: "/api/:path*", destination: `${apiTarget}/api/:path*` },
      { source: "/files/:path*", destination: `${apiTarget}/files/:path*` },
      { source: "/healthz", destination: `${apiTarget}/healthz` },
      { source: "/readyz", destination: `${apiTarget}/readyz` },
    ];
  },
};

export default config;
