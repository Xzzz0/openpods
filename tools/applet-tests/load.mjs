// Loads a QML ".pragma library" JS file in node: strips the pragma and returns the named top-level symbols.
import { readFileSync } from "node:fs";
export function load(path, names) {
  const src = readFileSync(new URL(path, import.meta.url), "utf8").replace(/^\.pragma library.*$/m, "");
  return new Function(`${src}\nreturn { ${names.join(", ")} };`)();
}
export function check(name, ok, info = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${info ? "  " + info : ""}`);
  if (!ok) process.exitCode = 1;
}
