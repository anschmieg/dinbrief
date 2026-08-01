const fs = require("node:fs");
const path = require("node:path");

const canonical = path.resolve(__dirname, "../../schemas/letter.schema.json");
const bundled = path.resolve(__dirname, "../letter.schema.json");
const expected = fs.readFileSync(canonical, "utf8");
const current = fs.existsSync(bundled) ? fs.readFileSync(bundled, "utf8") : "";

if (process.argv.includes("--check")) {
  if (current !== expected) {
    console.error("letter.schema.json is stale; run: npm run sync-schema");
    process.exitCode = 1;
  }
} else {
  fs.writeFileSync(bundled, expected);
}
