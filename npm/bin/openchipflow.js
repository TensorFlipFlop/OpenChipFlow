#!/usr/bin/env node

const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");

function resolvePython() {
  for (const candidate of ["python3", "python"]) {
    const probe = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (probe.status === 0) return candidate;
  }
  return null;
}

const python = resolvePython();
if (!python) {
  console.error("[openchipflow] python3/python not found in PATH");
  process.exit(127);
}

const packageRoot = path.resolve(__dirname, "..", "..");
const runner = path.join(packageRoot, "scripts", "runner.py");

const child = spawn(python, [runner, ...process.argv.slice(2)], {
  cwd: process.cwd(),
  stdio: "inherit",
  env: process.env,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
