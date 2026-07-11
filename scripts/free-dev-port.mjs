import { execSync } from "node:child_process";

const ports = process.argv.slice(2).map((value) => Number.parseInt(value, 10)).filter((port) => Number.isInteger(port) && port > 0);

if (ports.length === 0) {
  console.error("Usage: node scripts/free-dev-port.mjs <port> [port...]");
  process.exit(1);
}

function freePortOnWindows(port) {
  try {
    const output = execSync(`netstat -ano | findstr ":${port}" | findstr LISTENING`, { encoding: "utf8" });
    const pids = new Set(
      output
        .split(/\r?\n/)
        .map((line) => line.trim().split(/\s+/).at(-1))
        .filter((pid) => pid && pid !== "0")
    );
    for (const pid of pids) {
      execSync(`taskkill /PID ${pid} /F`, { stdio: "ignore" });
      console.log(`[dev] freed port ${port} (PID ${pid})`);
    }
  } catch {
    // No listener on this port.
  }
}

function freePortOnUnix(port) {
  try {
    execSync(`lsof -ti tcp:${port} | xargs -r kill -9`, { stdio: "ignore", shell: true });
    console.log(`[dev] freed port ${port}`);
  } catch {
    // No listener on this port.
  }
}

for (const port of ports) {
  if (process.platform === "win32") {
    freePortOnWindows(port);
  } else {
    freePortOnUnix(port);
  }
}
