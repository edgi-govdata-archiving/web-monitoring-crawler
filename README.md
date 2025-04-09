[![Code of Conduct](https://img.shields.io/badge/%E2%9D%A4-code%20of%20conduct-blue.svg?style=flat)][conduct] &nbsp;[![Project Status Board](https://img.shields.io/badge/✔-Project%20Status%20Board-green.svg?style=flat)][project]


# EDGI Web Monitoring Crawler

This repo contains tools and scripts for automating regular crawls of web pages that EDGI is actively monitoring as part of its Web Governance project. The goal is to create archive-ready captures of web content and store it in the Internet Archive, EDGI’s own cloud storage, and import analyzable metadata into [Web-Monitoring-DB][]

⚠️ **This is a messy experiment right now!** In the past, we relied on partner organizations (e.g. the Internet Archive) or monitoring services (e.g. Versionista, PageFreezer, Visualping, etc.) to do our crawling, and focused our work on analysis and workflow tools. This year, we are taking on more of the crawling work ourselves, but have mainly been managing crawls by hand with a bunch of one-off scripts. This repository aims to better organize and automate that work.

There is currently no standardized PR or contribution process for this project right now — work is very free-form. [EDGI’s Code of Conduct](#code-of-conduct) stil applies.


## Architecture/Roadmap

The scheduled crawls here currently run on GitHub Actions: it is free, convenient, and gives us some *really* nice workflow management. The basic setup is that there are two jobs:

1. `setup` Grabs all the actively monitored URLs from the database and writes them out as a set of Browsertrix config files (via `edgi-wm-crawler multi-seeds`).

    This does some fancy footwork to break things down into a set of crawls that can be run in parallel. It tries to keep each primary domain in a single crawl (except ones that are really big, like `epa.gov`) so that there’s minimal duplication of page resources across crawls (i.e. less duplicated stuff between the WARC files each crawl generates) and so the number of concurrent requests to a given domain is kept down. This is *also* necessary because GH actions jobs don’t have enough disk space to store the results from all the crawls together, but the other benefits are important, too!

2. `crawl` runs a crawl for each of the config files generated in step 1. This is a matrix job, so all the crawls run efficiently in parallel.

    After the crawl finishes, this job also:
    1. Saves the results as a GH actions artifact (even if the crawl fails, so it can be inspected).
    2. Uploads results to S3.
    3. Imports the results to web-monitoring-db.
    4. Uploads the WARC files to the Internet Achive.

    Ideally these follow-on bits would be separate jobs, but I don’t think there’s a way to do that in the current workflow syntax.

For now, this seems to work really well — it gets the crawls done quickly and efficiently, and splits work in a relatively smart way with (I think?) minimal duplication of subresources.

However, we might outgrow GH Actions at some point or have IP address blocking issues (honestly I’m surprised actions IP addresses aren’t already blocked!). Crawls have historically worked perfectly for us in AWS with a public, elastic IP. Some possible options:

- Keep it simple, just customize the `webrecorder/browsertrix-crawler` Docker image to include scripts to grab the seeds and do the uploading importing stuff before/after the crawl. Schedule that on ECS (with EventBridge) or our Kubernetes cluster (as a CronJob).

    The main downside here is that we go back to only having a few large, probably less efficient crawls. There’s not an easy way to manage the workflow of creating a dynamic number of parallel crawls here.

    The big upside is that this is really simple, and easy to deploy on any infrastructure.

- AWS Batch has [array jobs](https://docs.aws.amazon.com/batch/latest/userguide/array_jobs.html) for parallel jobs, but you can’t set the number of parallel jobs dynamically. The first job would need to schedule the follow-on jobs.

    Worth noting: Kubernetes has [“indexed jobs”](https://kubernetes.io/docs/tasks/job/indexed-parallel-processing-static/), which fill a similar role. They would also require having the first job create the subsequent jobs, which feels like a little more of a bear to me in Kubernetes than AWS Batch, but whatever.

- [AWS Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/getting-started.html) is a more purpose-built system for nice workflow automation like this. But it is a complex and very-custom AWS thing. We’d want to use the [“Map” state ](https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html) to run the crawls after generating configs.

- Apache Airflow is a nice system (with a fancy visual UI) that handles this kind of stuff well. You can dynamically map results of one job across subsequent parallel jobs with [`expand()`](https://airflow.apache.org/docs/apache-airflow/stable/authoring-and-scheduling/dynamic-task-mapping.html#task-generated-mapping). This is a lot more complicated to deploy effectively, but [AWS has a managed version](https://aws.amazon.com/managed-workflows-for-apache-airflow/).

Step functions and Airflow are fairly equivalent; the difference is mainly portability and cost — Airflow is portable to other platforms, but also more expensive and higher-overhead to run than step functions.


## Code of Conduct

This repository falls under EDGI’s [Code of Conduct][conduct].


## License & Copyright

Copyright (C) 2025 Environmental Data and Governance Initiative (EDGI)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3.0.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the [`LICENSE`](https://github.com/edgi-govdata-archiving/web-monitoring-crawler/blob/main/LICENSE) file for details.


[conduct]: https://github.com/edgi-govdata-archiving/overview/blob/main/CONDUCT.md
[project]: https://github.com/orgs/edgi-govdata-archiving/projects/32
[web-monitoring-db]: https://github.com/edgi-govdata-archiving/web-monitoring-db
