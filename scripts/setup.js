const { spawnSync } = require("node:child_process");
const { findPython } = require("./python");

const python = findPython();

if (!python) {
  console.error("No se encontro Python. Instala Python o define la variable PYTHON con la ruta al ejecutable.");
  process.exit(1);
}

const packages = ["pillow", "pymupdf", "pytesseract"];
console.log(`Instalando dependencias: ${packages.join(", ")}`);

const result = spawnSync(
  python.cmd,
  [...python.args, "-m", "pip", "install", ...packages],
  { stdio: "inherit", shell: false }
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 0);
