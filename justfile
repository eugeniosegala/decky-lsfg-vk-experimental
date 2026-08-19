default:
    echo "Available recipes: check, unit-test, local-package, local-engine-package, publish-package, build, deploy, logs, clean, generate-schema"
    echo "  just check            Run the local CI-equivalent quality gate"
    echo "  just unit-test        Run Python unit tests"
    echo "  just local-package    Build the Decky ZIP locally"
    echo "  just local-engine-package  Build engine + Decky ZIP from ../lsfg-vk"
    echo "  just publish-package  Build, tag, push, and publish the GitHub prerelease"
    echo "  just deploy deck@HOST  Copy the built ZIP to a chosen Deck host"
    echo "  just logs deck@HOST    Follow the plugin journal on a chosen Deck host"

generate-schema:
    python3 scripts/generate_ts_schema.py

check:
    pnpm check

unit-test:
    pnpm test

build:
    python3 scripts/generate_ts_schema.py && sudo rm -rf node_modules && .vscode/build.sh

local-package:
    scripts/package-local.sh

local-engine-package engine_repo="../lsfg-vk":
    scripts/package-local.sh --local-engine-repo "{{engine_repo}}"

publish-package:
    scripts/publish-package.sh

deploy deck_host:
    scp "out/Decky.LSFG-VK.Experimental.zip" "{{deck_host}}:~/Desktop"

logs deck_host:
    ssh "{{deck_host}}" "journalctl -f"

cef:
    tail -f ~/.local/share/Steam/logs/cef_log.txt 

clean:
    rm -rf node_modules dist
    sudo rm -rf /tmp/decky
