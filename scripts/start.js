const { spawnSync } = require("node:child_process");
const { existsSync } = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = path.join(root, "duplicate_image_app.py");
const userArgs = process.argv.slice(2);

if (!existsSync(app)) {
  console.error(`No se encontro la app: ${app}`);
  process.exit(1);
}

const candidates = [];
if (process.env.PYTHON) {
  candidates.push({ cmd: process.env.PYTHON, args: [] });
}
candidates.push(
  { cmd: "python", args: [] },
  { cmd: "py", args: ["-3"] },
  { cmd: "python3", args: [] }
);

for (const candidate of candidates) {
  const result = spawnSync(
    candidate.cmd,
    [...candidate.args, app, ...userArgs],
    { cwd: root, stdio: "inherit", shell: false }
  );

  if (result.error && result.error.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 0);
}

console.error("No se encontro Python. Instala Python o define la variable PYTHON con la ruta al ejecutable.");
process.exit(1);
