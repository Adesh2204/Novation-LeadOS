import { cpSync } from "node:fs";
import { spawn } from "node:child_process";

cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
const server = spawn(process.execPath, [".next/standalone/server.js"], {
  stdio: "inherit", env: { ...process.env, HOSTNAME: "0.0.0.0", PORT: process.env.PORT || "3000" },
});
process.on("SIGTERM", () => server.kill("SIGTERM"));
process.on("SIGINT", () => server.kill("SIGINT"));
server.on("exit", code => process.exit(code || 0));
