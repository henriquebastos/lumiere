// Print HyperFrames' single-file bundle of a project: node hyperframes_bundle.mjs <modules> <project>
// <modules> is a directory whose node_modules holds @hyperframes/core. The compiler is found
// through that package's own exports map, so this file needs no install of its own.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [modules, project] = process.argv.slice(2);
process.on("uncaughtException", (error) => { // one line, the reason: Node's own report ends with its version
  process.stderr.write(`${String(error?.message ?? error).split("\n")[0]}\n`);
  process.exit(1);
});
const core = join(modules, "node_modules", "@hyperframes", "core");
const entry = JSON.parse(readFileSync(join(core, "package.json"), "utf8")).exports["./compiler"].import;
const { bundleToSingleHtml } = await import(pathToFileURL(join(core, entry)).href);
console.log = console.error; // the bundler's notes must not land in the page
process.stdout.write(await bundleToSingleHtml(project));
