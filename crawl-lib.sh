#!/usr/bin/env bash
set -eo pipefail

BROWSERTRIX_IMAGE="${BROWSERTRIX_IMAGE:-webrecorder/browsertrix-crawler:1.9.3}"

# Any preliminary stuff we want to make sure is done before starting a crawl.
function prepare() {
    docker pull "${BROWSERTRIX_IMAGE}"
}

function pretty_format_crawl_log() {
    jq --unbuffered --raw-output '
        if .context == "crawlStatus" then
            "\(.timestamp) - \(.details.crawled)/\(.details.total) "
            + (
                (.details.crawled | tonumber) / (.details.total | tonumber)
                * 10000
                | round
                / 100
                | tostring
            )
            + "%"
        else
            "\(.timestamp) - \(.message) \(.details | tojson)"
        end
    '
}

function do_crawl() {
    input_config="${1}"
    collection="${2}"
    crawls_path="${PWD}/crawls"
    crawl_output="${crawls_path}/collections/${collection}"

    state_path="${crawl_output}/crawls"
    crawl_config="${state_path}/config.${collection}.yaml"
    mkdir -p "${state_path}"
    cp "${input_config}" "${crawl_config}"

    # TODO: should use `--restartsOnError` and check exit code and endlessly
    # restart instead of the current approach.
    for i in {1..10}; do
        if [[ "${i}" == "1" ]]; then
            echo "Starting crawl ${collection}"
        else
            echo "Pausing beteen tries..."
            sleep 60
            echo "Resuming crawl ${collection} (try #${i})"
        fi

        # Currently using `--attach` instead of `--tty`; not totally sure if
        # the latter would be better or have problematic edge cases.
        #
        # Using `--interactive` causes output formatting issues and is a no-go.
        # It also causes ctrl+c to interrupt the crawl and cause a retry
        # instead of interrupting the whole process.
        #
        # TODO: Look into whether we should set `--restartsOnError`. Not really
        # clear on how to use it right/what it does. It makes *fatal* errors
        # have an exit code of 0 (maybe problematic!) and also looks like it
        # changes how browser crashes are handled (I *think* this will cause
        # an exit with code 10 instead of trying to restart the browser).
        #
        # shellcheck disable=SC2310
        docker run \
            --rm \
            --attach stdout --attach stderr \
            --volume "${crawl_config}:/app/config.yaml" \
            --volume "${crawls_path}:/crawls/" \
            "${BROWSERTRIX_IMAGE}" \
            crawl \
            --config /app/config.yaml \
            --collection "${collection}" \
            --saveState always \
            | grep --line-buffered -E 'crawlStatus|"logLevel":\s?"error"' \
            | pretty_format_crawl_log \
            || true

        last_log="$(ls -tr "${crawl_output}/logs/" | tail -n 1)"
        logfile="${crawl_output}/logs/${last_log}"
        if [[ ! -f "${logfile}" ]]; then
            echo "Can't find log output file at '${logfile}'"
            false
        fi

        # TODO: Browsertrix now has nice, meaningful error codes. Should we be
        # using those instead of the last log lines?
        # https://crawler.docs.browsertrix.com/user-guide/exit-codes/
        interrupted="$(tail -n 3 "${logfile}" | grep -i 'crawl status: interrupted' || true)"
        if [[ -n "${interrupted}" ]]; then
            last_state="$(ls -tr "${state_path}" | tail -n 1)"
            crawl_config="${crawl_output}/crawls/${last_state}"

            echo "${collection} was interrupted!"
            echo ""
        else
            return 0
        fi
    done

    return 1
}
