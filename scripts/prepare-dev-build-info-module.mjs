import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectDirectory = path.resolve(scriptDirectory, "..");

export const prepareDevBuildInfoModule = async ({
  developmentBuildInfoPath = process.env.LSFGVK_DEV_BUILD_INFO_PATH,
  outputPath = path.join(projectDirectory, "src", "config", "devBuildInfo.generated.ts")
} = {}) => {
  const developmentBuildInfo = developmentBuildInfoPath
    ? JSON.parse(await readFile(developmentBuildInfoPath, "utf8"))
    : null;

  await writeFile(
    outputPath,
    "import type { LocalDevelopmentBuildInfo } from \"./devBuildInfo\";\n\n" +
      "export const localDevelopmentBuildInfo: LocalDevelopmentBuildInfo | null = " +
      `${JSON.stringify(developmentBuildInfo, null, 2)};\n`,
    "utf8"
  );
};

const invokedPath = process.argv[1] && path.resolve(process.argv[1]);
if (invokedPath === fileURLToPath(import.meta.url)) {
  await prepareDevBuildInfoModule();
}
