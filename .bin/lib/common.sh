#!/bin/bash

function setRoot() {
    ROOT_PATH=$PWD
    while [[ $ROOT_PATH != / ]]; do
        output=$(find "$ROOT_PATH" -maxdepth 1 -mindepth 1 -name "pyproject.toml")
        if [[ -n $output ]]; then
            break
        fi
        # Note: if you want to ignore symlinks, use "$(realpath -s "$path"/..)"
        ROOT_PATH="$(readlink -f "$ROOT_PATH"/..)"
    done

    if [[ $ROOT_PATH == / ]]; then
        ROOT_PATH=$( realpath $( dirname "${BASH_SOURCE[0]}" )/../../ )
        echo "Could not find \`pyproject.toml\`, following back to $( basename $ROOT_PATH )"
    else
        echo "Using project $( basename $ROOT_PATH )"
    fi
}
