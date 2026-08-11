import { rollup } from "rollup";
import config from "../rollup.config.js";

try {
  const configurations = Array.isArray(config) ? config : [config];

  for (const configuration of configurations) {
    const { output, watch: _watch, ...inputOptions } = configuration;
    const outputs = Array.isArray(output) ? output : [output];
    const bundle = await rollup(inputOptions);

    try {
      for (const outputOptions of outputs) {
        if (!outputOptions) {
          throw new Error("Rollup configuration is missing output options");
        }
        await bundle.write(outputOptions);
      }
    } finally {
      await bundle.close();
    }
  }

  // Some Decky Rollup plugin versions retain background handles after a
  // successful one-shot build. All output has been written and closed here,
  // so exit explicitly instead of leaving package scripts waiting forever.
  process.exit(0);
} catch (error) {
  console.error(error);
  process.exit(1);
}
