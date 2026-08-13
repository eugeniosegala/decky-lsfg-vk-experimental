default:
    echo "Available recipes: local-package, local-engine-package, publish-package, build, test, clean, generate-schema"
    echo "  just local-package    Build the Decky ZIP locally"
    echo "  just local-engine-package  Build engine + Decky ZIP from ../lsfg-vk"
    echo "  just publish-package  Build, tag, push, and publish the GitHub prerelease"

generate-schema:
    python3 scripts/generate_ts_schema.py

build:
    python3 scripts/generate_ts_schema.py && sudo rm -rf node_modules && .vscode/build.sh

local-package:
    scripts/package-local.sh

local-engine-package engine_repo="../lsfg-vk":
    scripts/package-local.sh --local-engine-repo "{{engine_repo}}"

publish-package:
    scripts/publish-package.sh

test:
    scp "out/Decky.LSFG-VK.Experimental.zip" deck@192.168.0.6:~/Desktop

watch:
    ssh deck@192.168.0.6 "journalctl -f"

cef:
    tail -f ~/.local/share/Steam/logs/cef_log.txt 

clean:
    rm -rf node_modules dist
    sudo rm -rf /tmp/decky
