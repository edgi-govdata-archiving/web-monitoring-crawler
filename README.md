[![Code of Conduct](https://img.shields.io/badge/%E2%9D%A4-code%20of%20conduct-blue.svg?style=flat)][conduct] &nbsp;[![Project Status Board](https://img.shields.io/badge/✔-Project%20Status%20Board-green.svg?style=flat)][project]


# EDGI Web Monitoring Crawler

This repo contains tools and scripts for automating regular crawls of web pages that EDGI is actively monitoring as part of its Web Governance project. The goal is to create archive-ready captures of web content and store it in the Internet Archive, EDGI’s own cloud storage, and import analyzable metadata into [Web-Monitoring-DB][]

⚠️ **This is a messy experiment right now!** In the past, we relied on partner organizations (e.g. the Internet Archive) or monitoring services (e.g. Versionista, PageFreezer, Visualping, etc.) to do our crawling, and focused our work on analysis and workflow tools. This year, we are taking on more of the crawling work ourselves, but have mainly been managing crawls by hand with a bunch of one-off scripts. This repository aims to better organize and automate that work.

There is currently no standardized PR or contribution process for this project right now — work is very free-form. [EDGI’s Code of Conduct](#code-of-conduct) stil applies.


## Roadmap

At current, the automation here runs on GitHub Actions because it makes it a little easier to organize various pieces that are not currently compatible with each other (e.g. some of our tooling depends on Python libraries that are not compatible with Python 3.11, but Browsertrix uses Python 3.12). GH actions is also free, which is convenient.

However, we will eventually outgrow this (we already operate near the time limit for GH actions) and need to switch to better tooling:
- Probably Dockerize the whole thing so it can be run in Kubernetes, ECS, or similar.
- More complex workflow management code than bash.
- Abstracting things so this can also be used for one-off crawls, not just the active URLs of the Web Governance project.


## Code of Conduct

This repository falls under EDGI’s [Code of Conduct][conduct].


## License & Copyright

Copyright (C) 2025 Environmental Data and Governance Initiative (EDGI)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 3.0.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

See the [`LICENSE`](https://github.com/edgi-govdata-archiving/webpage-versions-processing/blob/main/LICENSE) file for details.


[conduct]: https://github.com/edgi-govdata-archiving/overview/blob/main/CONDUCT.md
[project]: https://github.com/orgs/edgi-govdata-archiving/projects/32
[web-monitoring-db]: https://github.com/edgi-govdata-archiving/web-monitoring-db
