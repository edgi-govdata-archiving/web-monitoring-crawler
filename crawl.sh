#!/usr/bin/env bash
set -eo pipefail

##
# Run this with the crawl config path and collection name, e.g:
#
#   ./crawl.sh ./config.yaml my-crawl-1
##

script_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
source "${script_dir}/crawl-lib.sh"

if [[ -z "${1}" ]] || [[ -z "${2}" ]]; then
    echo 'Usage: crawl.sh CONFIG_PATH COLLECTION_NAME'
    echo ''
    echo 'Example: `./crawl.sh ./config.yaml my-crawl-1`'
    exit 1
fi

mkdir -p crawls
do_crawl "${1}" "${2}"
