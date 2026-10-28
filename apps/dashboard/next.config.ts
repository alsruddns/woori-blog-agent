import type { NextConfig } from "next";
const isolatedUiTest = process.env.WOORI_TEST_MODE === "1" && process.env.NODE_ENV !== "production";
const config: NextConfig = {
  logging: false,
  ...(isolatedUiTest ? { distDir: ".next-p5-code014" } : {}),
};
export default config;
