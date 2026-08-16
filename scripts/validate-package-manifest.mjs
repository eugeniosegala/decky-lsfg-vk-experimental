#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { basename } from "node:path";

const SAFE_VERSION = /^[0-9A-Za-z][0-9A-Za-z.+-]*$/;
const SHA256 = /^[0-9a-f]{64}$/i;
const GIT_COMMIT = /^[0-9a-f]{40}$/i;
const ARCHIVE_NAME = /^[0-9A-Za-z][0-9A-Za-z._+-]*\.tar\.xz$/;
const GITHUB_REPOSITORY = /^[0-9A-Za-z_.-]+\/[0-9A-Za-z_.-]+$/;

function fail(message) {
  throw new Error(message);
}

function loadManifest(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function requireString(value, field, { pattern, maximumLength = 512 } = {}) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maximumLength ||
    /[\u0000-\u001f\u007f-\u009f]/u.test(value) ||
    (pattern && !pattern.test(value))
  ) {
    fail(`package.json has invalid ${field}`);
  }
  return value;
}

function validateGithubSourceRepository(value, field) {
  const repository = requireString(value, field);
  let parsed;
  try {
    parsed = new URL(repository);
  } catch {
    fail(`package.json has invalid ${field}`);
  }
  const path = parsed.pathname.replace(/^\//, "").replace(/\/$/, "");
  if (
    parsed.protocol !== "https:" ||
    parsed.hostname !== "github.com" ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    !GITHUB_REPOSITORY.test(path) ||
    repository !== `https://github.com/${path}`
  ) {
    fail(`package.json has invalid ${field}`);
  }
  return repository;
}

function validatePackageRepository(value) {
  const repositoryUrl = requireString(value, "repository.url");
  const match = repositoryUrl.match(
    /^git\+https:\/\/github\.com\/([0-9A-Za-z_.-]+\/[0-9A-Za-z_.-]+)\.git$/,
  );
  if (!match || !GITHUB_REPOSITORY.test(match[1])) {
    fail("package.json has invalid repository.url");
  }
  return match[1];
}

function validateArchiveName(value, field) {
  const name = requireString(value, field, { pattern: ARCHIVE_NAME });
  if (basename(name) !== name || name === "." || name === "..") {
    fail(`package.json has invalid ${field}`);
  }
  return name;
}

function validateReleaseAssetUrl(value, field, sourceRepository, releaseTag, name) {
  const url = requireString(value, field, { maximumLength: 2048 });
  const expected = `${sourceRepository}/releases/download/${releaseTag}/${name}`;
  if (url !== expected) {
    fail(`package.json has invalid ${field}; expected ${expected}`);
  }
  return url;
}

function validateRemoteBinary(manifest) {
  if (!Array.isArray(manifest.remote_binary) || manifest.remote_binary.length !== 1) {
    fail("package.json must define exactly one remote_binary entry");
  }

  const [binary] = manifest.remote_binary;
  if (!binary || typeof binary !== "object" || Array.isArray(binary)) {
    fail("package.json must define one versioned, verified remote_binary entry");
  }

  const version = requireString(binary.version, "remote_binary.version", {
    pattern: SAFE_VERSION,
  });
  requireString(binary.lineage_version, "remote_binary.lineage_version", {
    pattern: SAFE_VERSION,
  });
  const releaseTag = requireString(binary.release_tag, "remote_binary.release_tag");
  if (releaseTag !== `v${version}`) {
    fail("package.json remote_binary.release_tag must equal v<version>");
  }
  const sourceRepository = validateGithubSourceRepository(
    binary.source_repository,
    "remote_binary.source_repository",
  );
  requireString(binary.source_commit, "remote_binary.source_commit", {
    pattern: GIT_COMMIT,
  });
  const name = validateArchiveName(binary.name, "remote_binary.name");
  validateReleaseAssetUrl(
    binary.url,
    "remote_binary.url",
    sourceRepository,
    releaseTag,
    name,
  );
  requireString(binary.sha256hash, "remote_binary.sha256hash", {
    pattern: SHA256,
  });

  const flatpak = binary.flatpak_bundle;
  if (flatpak !== undefined) {
    if (!flatpak || typeof flatpak !== "object" || Array.isArray(flatpak)) {
      fail("flatpak_bundle must be an object when present");
    }
    const flatpakName = validateArchiveName(
      flatpak.name,
      "remote_binary.flatpak_bundle.name",
    );
    validateReleaseAssetUrl(
      flatpak.url,
      "remote_binary.flatpak_bundle.url",
      sourceRepository,
      releaseTag,
      flatpakName,
    );
    requireString(
      flatpak.sha256hash,
      "remote_binary.flatpak_bundle.sha256hash",
      { pattern: SHA256 },
    );
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
  requireString(manifest.version, "version", { pattern: SAFE_VERSION });
  const githubRepository = validatePackageRepository(manifest.repository?.url);

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

function validateManifest(manifest) {
  validateRemoteBinary(manifest);
  requireString(manifest.version, "version", { pattern: SAFE_VERSION });
  validatePackageRepository(manifest.repository?.url);
}

function main([mode, manifestPath]) {
  if (!mode || !manifestPath) {
    fail(
      "Usage: validate-package-manifest.mjs " +
        "<check|package-local|publish-package> <package.json>",
    );
  }

  const manifest = loadManifest(manifestPath);
  let fields;
  if (mode === "check") {
    validateManifest(manifest);
    return;
  } else if (mode === "package-local") {
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
