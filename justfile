default:
    echo "Available recipes: package, publish, build, test, clean, generate-schema"
    echo "  just package  Build the Decky ZIP locally"
    echo "  just publish  Build, tag, push, and publish the GitHub prerelease"

generate-schema:
    python3 scripts/generate_ts_schema.py

build:
    python3 scripts/generate_ts_schema.py && sudo rm -rf node_modules && .vscode/build.sh

package-release:
    scripts/package-release.sh

publish-release:
    scripts/package-release.sh --publish

# Short, day-to-day release commands. The longer names remain as compatibility aliases.
package: package-release

publish: publish-release

test:
    scp "out/Decky.LSFG-VK.Experimental.zip" deck@192.168.0.6:~/Desktop

watch:
    ssh deck@192.168.0.6 "journalctl -f"

cef:
    tail -f ~/.local/share/Steam/logs/cef_log.txt 

clean:
    rm -rf node_modules dist
    sudo rm -rf /tmp/decky
