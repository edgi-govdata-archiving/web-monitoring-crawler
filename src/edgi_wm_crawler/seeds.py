from collections import defaultdict
from itertools import chain
import re
from typing import Any, Generator, Iterable, Literal
from urllib.parse import urlparse
import yaml
from web_monitoring.db import Client as DbClient


# We track these, but they are known to be dead servers (so will produce
# network-level errors). We'll keep an eye on them via separate means.
DEAD_SERVER_URLS = [
    'https://ejscorecard.geoplatform.gov/about/',
    'https://ejscorecard.geoplatform.gov/contact/',
    'https://ejscorecard.geoplatform.gov/en/scorecard/environmental-protection-agency/',
    'https://ejscorecard.geoplatform.gov/scorecard/',
    'https://energyjustice-schools.egs.anl.gov/',
    'https://energyjustice.egs.anl.gov/',
    'https://screeningtool.geoplatform.gov/en/',
    'https://screeningtool.geoplatform.gov/en/about',
    'https://screeningtool.geoplatform.gov/en/contact',
    'https://screeningtool.geoplatform.gov/en/downloads',
    'https://screeningtool.geoplatform.gov/en/frequently-asked-questions',
    'https://screeningtool.geoplatform.gov/en/methodology',
    'https://screeningtool.geoplatform.gov/en/previous-versions',
    'https://screeningtool.geoplatform.gov/en/public-engagement',
    'https://www.environmentaljustice.gov/',
    'https://www.environmentaljustice.gov/actions/',
    'https://www.environmentaljustice.gov/resources/',
    'https://www.environmentaljustice.gov/stories/',
    'https://www.environmentaljustice.gov/wh-office-ej/',
    'https://ejscreen.epa.gov/mapper/',
]

# These are known to return 404 status codes with empty bodies (and we expect
# them to stay that way). This breaks Browsertrix right now:
# https://github.com/webrecorder/browsertrix-crawler/issues/789
UNCRAWLABLE_404_URLS = [
    'https://www.whitehouse.gov/wp-content/uploads/2023/01/01-2023-Framework-for-Federal-Scientific-Integrity-Policy-and-Practice.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/03/FTAC_Report_03222023_508.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/09/National-Climate-Resilience-Framework-FINAL.pdf',
    'https://www.whitehouse.gov/wp-content/uploads/2023/06/OSTP-SCIENTIFIC-INTEGRITY-POLICY.pdf',
]

IGNORE_URLS = frozenset([*DEAD_SERVER_URLS, *UNCRAWLABLE_404_URLS])


def active_urls(pattern: str | None = None) -> Generator[str, None, None]:
    # TODO: pattern negation support should be built into the API.
    antipattern = None
    if pattern and pattern.startswith('!'):
        antipattern = re.compile('^' + pattern[1:].replace('*', '.*') + '$')
        pattern = None

    urls = (
        page['url']
        for page in DbClient.from_env().get_pages(active=True, url=pattern)
        if page['url'] not in IGNORE_URLS
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
