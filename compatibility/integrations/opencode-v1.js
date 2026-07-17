// codex-axi managed ambient context plugin
import { spawn } from "node:child_process";

const command = "codex-axi";
const timeoutMs = 10000;

function dashboard(cwd) {
  return new Promise((resolve) => {
    const child = spawn(command, [], {
      cwd: typeof cwd === "string" && cwd.length > 0 ? cwd : process.cwd(),
      env: process.env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      resolve("error: codex-axi dashboard timed out");
    }, timeoutMs);
    child.stdout?.setEncoding("utf-8");
    child.stderr?.setEncoding("utf-8");
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve("error: codex-axi dashboard failed: " + error.message);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(code === 0 ? stdout.trim() : "error: " + (stderr || stdout).trim());
    });
  });
}

export const CodexAxiAmbientContextPlugin = async ({ directory }) => {
  const cache = new Map();
  return {
    "experimental.chat.system.transform": async (input, output) => {
      const session = input.sessionID ?? "__global__";
      if (!cache.has(session)) cache.set(session, await dashboard(directory));
      const value = cache.get(session);
      if (value) output.system.push("## AXI ambient context: codex-axi\n" + value);
    },
  };
};
