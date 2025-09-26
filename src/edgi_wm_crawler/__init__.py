from concurrent.futures import as_completed, ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import batched
import json
from pathlib import Path
from sys import exit, stderr
from typing import Iterable
from web_monitoring.db import Client as DbClient
from .seeds import (
    active_urls,
    check_connection_error,
    format_text,
    format_browsertrix,
    group_urls,
)

PRECHECK_FILE_NAME = 'precheck.log.json'


def main() -> None:
    from argparse import ArgumentParser

    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    seeds_command = subparsers.add_parser('seeds', help='Generate crawler seeds')
    seeds_command.add_argument(
        '--format',
        choices=('text', 'browsertrix'),
        default='text',
        help='Format of seeds output.'
    )
    seeds_command.add_argument(
        '--pattern',
        help='Only list URLs matching this pattern.'
    )
    seeds_command.add_argument(
        '--workers',
        type=int,
        default=4,
        help='How many workers (browserstrix only).'
    )
    seeds_command.add_argument(
        '--precheck-connections',
        type=bool,
        help=(
            'Filter out hosts that are unreachable (DNS resolution errors, '
            'connection timeouts, etc.).'
        )
    )
    seeds_command.set_defaults(func=generate_seeds)

    multi_seeds_command = subparsers.add_parser(
        'multi-seeds',
        help='Generate multiple seed lists of at most `size` URLs',
        description=(
            'Generate multiple seed list files in the `--output` directory. '
            'Seed URLs are grouped by primary domain (e.g. "epa.gov") and '
            'groups are packed into seed lists of up to `--size` URLs each. '
            'If a single group has more than `--size` URLs, it will be broken '
            'into files of `--single-group-size` (if set) or `--size` URLs.'
        )
    )
    multi_seeds_command.add_argument(
        '--format',
        choices=('text', 'browsertrix'),
        default='text',
        help='Format of seeds output.'
    )
    multi_seeds_command.add_argument(
        '--pattern',
        help='Only list URLs matching this pattern.'
    )
    multi_seeds_command.add_argument(
        '--workers',
        type=int,
        default=2,
        help='How many workers (browserstrix only).'
    )
    multi_seeds_command.add_argument(
        '--size',
        type=int,
        default=1000,
        help='How many URLs per seed list.'
    )
    multi_seeds_command.add_argument(
        '--single-group-size',
        type=int,
        default=0,
        help=(
            'If a single group has more than `size` entries, break it into '
            'seed lists of this many URLs each (defaults to value of `size`).'
        )
    )
    multi_seeds_command.add_argument(
        '--output',
        type=Path,
        default=Path('.'),
        help='Directory to write seed lists to.'
    )
    multi_seeds_command.add_argument(
        '--precheck-connections',
        action='store_true',
        help=(
            'Filter out hosts that are unreachable (DNS resolution errors, '
            'connection timeouts, etc.).'
        )
    )
    multi_seeds_command.set_defaults(func=generate_multi_seeds)

    import_precheck_command = subparsers.add_parser('import-precheck', help='Import precheck results to web-montioring-db')
    import_precheck_command.add_argument(
        'seeds_dir',
        type=Path,
        help='Path to seeds output directory.'
    )
    import_precheck_command.set_defaults(func=import_precheck)

    args = parser.parse_args()
    args.func(**vars(args))


def generate_seeds(*, format, pattern, workers, precheck_connections, **_kwargs) -> None:
    print(f'Generating seeds as {format}...', file=stderr)
    urls = active_urls(pattern=pattern)
    if precheck_connections:
        urls = filter_unreachable_hosts(urls)
    if format == 'text':
        print(format_text(urls))
    elif format == 'browsertrix':
        print(format_browsertrix(urls, workers=workers))
    else:
        print(f'Unknown format: "{format}"', file=stderr)
        exit(1)


def generate_multi_seeds(*, pattern, workers: int, output: Path, size: int, single_group_size: int = 0, precheck_connections: bool, **_kwargs) -> None:
    single_group_size = single_group_size or size

    print(f'Writing seed files to "{output}/*"...', file=stderr)
    output.mkdir(parents=True, exist_ok=True)
    filename_template = '{name}.seeds.yaml'

    files = []

    urls = active_urls(pattern=pattern)
    if precheck_connections:
        urls = filter_unreachable_hosts(urls, output_dir=output)
    core_groups = group_urls(urls, by='domain')

    oversized = [k for k, v in core_groups.items() if len(v) >= size]
    for group in oversized:
        urls = core_groups.pop(group)
        for index, subset in enumerate(batched(urls, single_group_size)):
            file_group = group.replace('.', '-')
            filename = filename_template.format(name=f'{file_group}-{index + 1}')
            with open(output / filename, 'w') as file:
                file.write(format_browsertrix(subset, workers=1))
                files.append(filename)
                print(f'Wrote "{file.name}"', file=stderr)

    subsets = []
    while len(core_groups):
        subset = []
        remaining = size
        for group, urls in core_groups.copy().items():
            if len(urls) <= remaining:
                core_groups.pop(group)
                subset.extend(urls)
                remaining -= len(urls)
                if remaining == 0:
                    break

        subsets.append(subset)

    for index, subset in enumerate(subsets):
        filename = filename_template.format(name=f'other-{index + 1}')
        with open(output / filename, 'w') as file:
            file.write(format_browsertrix(subset, workers=workers))
            files.append(filename)
            print(f'Wrote "{file.name}"', file=stderr)

    print(json.dumps([f.split('.seeds')[0] for f in files]))


def import_precheck(*, seeds_dir: Path, **_kwargs) -> None:
    hosts = {}
    precheck_path = seeds_dir / PRECHECK_FILE_NAME
    with precheck_path.open('r') as precheck_file:
        hosts = json.load(precheck_file)

    error_records = []
    for info in hosts.values():
        for url in info.get('urls', []):
            error_records.append({
                'url': url,
                'capture_time': info['timestamp'],
                'network_error': info['error'],
                'source_type': 'edgi_crawl',
                'source_metadata': {},
            })

    print(f'Importing {len(error_records)} recordings of network errors...')
    client = DbClient.from_env()
    import_ids = client.add_versions(error_records)
    errors = client.monitor_import_statuses(import_ids)
    total = sum(len(job_errors) for job_errors in errors.values())
    if total > 0:
        print('Import job errors:')
        for job_id, job_errors in errors.items():
            print(f'  {job_id}: {len(job_errors):>3} errors {job_errors}')
        print(f'  Total: {total:>3} errors')
    else:
        print(f'{len(import_ids)} import jobs completed successfully.')


def filter_unreachable_hosts(urls: Iterable[str], output_dir: Path | None = None) -> list[str]:
    host_groups = group_urls(urls, by='host')

    print(f'Pre-checking {len(host_groups)} hosts for connection failures...', file=stderr)

    urls = []
    log_data = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        host_futures = {
            executor.submit(check_connection_error, host_urls[0]): host
            for host, host_urls in host_groups.items()
        }
        for future in as_completed(host_futures):
            host = host_futures[future]
            error = future.result()
            log_data[host] = {
                'timestamp': datetime.now(tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
                'error': error,
                'urls': [],
            }
            if error:
                print(f'❌ {host} (Error: {error})', file=stderr)
                log_data[host]['urls'] = host_groups[host]
            else:
                print(f'✅ {host}', file=stderr)
                urls.extend(host_groups[host])

    if output_dir:
        log_path = output_dir / PRECHECK_FILE_NAME
        with log_path.open('w') as log_file:
            json.dump(log_data, log_file)

    return urls
