#!/usr/bin/env node

import { readFileSync } from "node:fs";

function fail(message) {
  throw new Error(message);
}

function loadManifest(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function validateRemoteBinary(manifest) {
  if (!Array.isArray(manifest.remote_binary) || manifest.remote_binary.length !== 1) {
    fail("package.json must define exactly one remote_binary entry");
  }

  const [binary] = manifest.remote_binary;
  if (!binary?.name || !binary?.version || !binary?.url || !binary?.sha256hash) {
    fail("package.json must define one versioned, verified remote_binary entry");
  }

  const flatpak = binary.flatpak_bundle;
  if (flatpak && (!flatpak.name || !flatpak.url || !flatpak.sha256hash)) {
    fail("flatpak_bundle must define name, url, and sha256hash when present");
  }

  return { binary, flatpak };
}

function packageLocalFields(manifest) {
  const { binary, flatpak } = validateRemoteBinary(manifest);
  return [
    binary.name,
    binary.version,
    binary.url,
    binary.sha256hash,
    flatpak?.name ?? "",
    flatpak?.url ?? "",
    flatpak?.sha256hash ?? "",
  ];
}

function publishPackageFields(manifest) {
  const { binary, flatpak } = validateRemoteBinary(manifest);
  const repositoryUrl = manifest.repository?.url;
  const githubRepository = repositoryUrl
    ?.replace(/^git\+https:\/\/github\.com\//, "")
    .replace(/\.git$/, "");

  if (!manifest.version || !githubRepository) {
    fail("package.json must define version and a GitHub repository");
  }

  return [
    binary.name,
    binary.version,
    manifest.version,
    githubRepository,
    flatpak ? "true" : "false",
    binary.url,
    binary.release_tag ?? "",
  ];
}

function main([mode, manifestPath]) {
  if (!mode || !manifestPath) {
    fail(
      "Usage: validate-package-manifest.mjs " +
        "<package-local|publish-package> <package.json>",
    );
  }

  const manifest = loadManifest(manifestPath);
  let fields;
  if (mode === "package-local") {
    fields = packageLocalFields(manifest);
  } else if (mode === "publish-package") {
    fields = publishPackageFields(manifest);
  } else {
    fail(`Unknown validation mode: ${mode}`);
  }

  process.stdout.write(`${fields.join("\t")}\n`);
}

try {
  main(process.argv.slice(2));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
