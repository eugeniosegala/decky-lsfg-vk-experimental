default:
    echo "Available recipes: local-package, publish-package, build, test, clean, generate-schema"
    echo "  just local-package    Build the Decky ZIP locally"
    echo "  just publish-package  Build, tag, push, and publish the GitHub prerelease"

generate-schema:
    python3 scripts/generate_ts_schema.py

build:
    python3 scripts/generate_ts_schema.py && sudo rm -rf node_modules && .vscode/build.sh

local-package:
    scripts/package-local.sh

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
