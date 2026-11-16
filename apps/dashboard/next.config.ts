import type { NextConfig } from "next";
const isolatedUiTest = process.env.WOORI_TEST_MODE === "1" && process.env.NODE_ENV !== "production";
const isolatedBuildDir = process.env.WOORI_DASHBOARD_DIST_DIR;
const safeIsolatedBuildDir = isolatedBuildDir && /^\.next-p5-[a-z0-9-]+$/.test(isolatedBuildDir)
  ? isolatedBuildDir
  : undefined;
const config: NextConfig = {
  logging: false,
  ...(safeIsolatedBuildDir ? { distDir: safeIsolatedBuildDir } : isolatedUiTest ? { distDir: ".next-p5-code014" } : {}),
};
export default config;
