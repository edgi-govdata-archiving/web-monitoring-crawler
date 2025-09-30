from collections import defaultdict
from itertools import chain
import requests
from requests.adapters import HTTPAdapter
import re
import threading
from typing import Any, Generator, Iterable, Literal
from urllib.parse import urlparse
from urllib3.util import Retry
import yaml
from web_monitoring.db import Client as DbClient


IGNORE_HOSTS = (
    # TODO: remove these entirely. These are all servers that are known to be
    # dead and that could cause crawl problems, but we now run prechecks that
    # largely resolve those issues and help us actually record that the server
    # is down, which is important (we also want to know if/when it comes back!).
    # Commenting these out for now in case we hit problems, but I intend to
    # remove them entirely in a week or so if nothing goes horribly awry.
    #
    # 'ejscorecard.geoplatform.gov',        # 4 URLs
    # 'energyjustice-schools.egs.anl.gov',  # 1 URL
    # 'energyjustice.egs.anl.gov',          # 1 URL
    # 'screeningtool.geoplatform.gov',      # 8 URLs
    # 'www.environmentaljustice.gov',       # 5 URLs
    # 'ejscreen.epa.gov',                   # 1 URL
    # 'www.globalchange.gov',
    # 'atlas.globalchange.gov',
    # 'health2016.globalchange.gov',
    # 'nca2023.globalchange.gov',
    # 'sealevel.globalchange.gov',
    # 'liftoff.energy.gov',
)

IGNORE_URLS = (
    # These are known to return 404 status codes with empty bodies (and we
    # expect them to stay that way). This breaks Browsertrix right now:
    # https://github.com/webrecorder/browsertrix-crawler/issues/789
    'https://www.whitehouse.gov/wp-content/uploads/2023/01/01-2023-Framework-for-Federal-Scientific-Integrity-Policy-and-Practice.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/03/FTAC_Report_03222023_508.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/09/National-Climate-Resilience-Framework-FINAL.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/06/OSTP-SCIENTIFIC-INTEGRITY-POLICY.pdf',
)


def active_urls(pattern: str | None = None) -> Generator[str, None, None]:
    # TODO: pattern negation support should be built into the API.
    antipattern = None
    if pattern and pattern.startswith('!'):
        antipattern = re.compile('^' + pattern[1:].replace('*', '.*') + '$')
        pattern = None

    urls = (
        page['url']
        for page in DbClient.from_env().get_pages(active=True, url=pattern)
        if (
            page['url'] not in IGNORE_URLS
            and urlparse(page['url']).hostname not in IGNORE_HOSTS
        )
    )
    if antipattern:
        urls = (
            url for url in urls
            if not antipattern.match(url)
        )

    return urls


def format_text(urls: Iterable[str]) -> str:
    return ''.join(
        f'{url}\n'
        for url in sorted(urls)
    )


def format_browsertrix(urls: Iterable[str], *, workers: int = 4, **options: Any) -> str:
    # Do some funky sorting to optimize for Browsertrix. We want arcgis URLs
    # all together or in a separate crawl because they tend to put a huge
    # amount of memory pressure on the browser, causing hangs or crashes.
    #
    # For other URLs we interleave the domains so that each one is receiving
    # a minimal rate of requests and we are less likely to trip crawl blockers.
    groups = group_urls(urls, by='domain')
    arcgis = groups.pop('arcgis', [])
    sorted_urls = chain(arcgis, interleave(*groups.values()))

    seeds = []
    for url in sorted_urls:
        if '#' in url:
            seeds.append({
                'url': url,
                'scopeType': 'page-spa',
                'depth': 0
            })
        else:
            seeds.append(url)

    return yaml.safe_dump({
        'workers': workers,
        'saveStateHistory': workers,
        'scopeType': 'page',
        'rolloverSize': 8_000_000_000,
        # Default timeout is 90, bump it up for some sites that seem to have long CloudFront timeouts.
        'pageLoadTimeout': 120,
        **options,
        'warcinfo': {
            'operator': '"Environmental Data & Governance Initiative" <contact@envirodatagov.org>',
            **options.get('warcinfo', {})
        },
        'seeds': seeds
    })


def group_urls(
    urls: Iterable[str],
    by: Literal['host', 'domain'] = 'domain'
) -> dict[str, list[str]]:
    url_groups: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        parsed = urlparse(url)
        assert parsed.hostname, f'No hostname: "{url}"'

        if by == 'host':
            group = parsed.hostname
        elif by == 'domain':
            group = '.'.join(parsed.hostname.split('.')[-2:])
            if 'arcgis' in parsed.hostname:
                group = 'arcgis'
        else:
            raise ValueError('"by" must be "host" or "domain"')

        url_groups[group].append(url)

    return url_groups


def interleave(*iterables):
    iterators = [iter(iterable) for iterable in iterables]
    while iterators:
        for iterator in iterators:
            try:
                yield next(iterator)
            except StopIteration:
                iterators.remove(iterator)


# Requests is not thread-safe, so store a separate session for each thread.
thread_requests = threading.local()


def check_connection_error(url: str) -> str | None:
    """
    Is it possible to connect to this server/hostname? Returns ``None`` for
    successful connections, otherwise a string indicating the type of
    connection failure.
    """
    if not hasattr(thread_requests, 'session'):
        thread_requests.session = requests.Session()
        # status=0 -> only retry network failures, not non-2xx HTTP statuses.
        retries = Retry(total=2, status=0, backoff_factor=2)
        thread_requests.session.mount('https://', HTTPAdapter(max_retries=retries))
        thread_requests.session.mount('http://', HTTPAdapter(max_retries=retries))

    # NOTE: we currently use a GET request here because some servers respond
    # to HEAD requests negatively(!) (really interestingly, `www.ncei.noaa.gov`
    # will respond to a HEAD request from cURL but not other tools (seems to be
    # based on the `User-Agent` header). Anyway, the simplest fix is to do a
    # full GET, although that's not fun if the response happens to be large!
    # It might be nicer to start with HEAD and fall back to GET on connection
    # resets and timeouts.
    response = None
    try:
        response = thread_requests.session.get(url, timeout=(60, 10))
        response.content
    except requests.exceptions.ConnectionError as error:
        message = str(error)
        if 'NameResolutionError' in message:
            return 'ERR_NAME_NOT_RESOLVED'
        elif 'ConnectTimeoutError' in message:
            return 'timeout'
        elif 'RemoteDisconnected' in message:
            return 'ERR_CONNECTION_RESET'
        else:
            # Ignore other types of connection errors, e.g. SSL failures, which
            # browsers (and our crawler) may handle less strictly.
            return None
    except Exception:
        return None
    finally:
        if response:
            response.close()
