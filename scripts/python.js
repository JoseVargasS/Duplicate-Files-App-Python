const { spawnSync } = require("node:child_process");

function pythonCandidates() {
  const candidates = [];
  if (process.env.PYTHON) {
    candidates.push({ cmd: process.env.PYTHON, args: [] });
  }
  candidates.push(
    { cmd: "python", args: [] },
    { cmd: "py", args: ["-3"] },
    { cmd: "python3", args: [] }
  );
  return candidates;
}

function findPython() {
  for (const candidate of pythonCandidates()) {
    const result = spawnSync(
      candidate.cmd,
      [...candidate.args, "-c", "import sys; print(sys.executable)"],
      { encoding: "utf8", shell: false }
    );

    if (result.error && result.error.code === "ENOENT") {
      continue;
    }
    if (result.status === 0) {
      return candidate;
    }
  }
  return null;
}

module.exports = { findPython };
