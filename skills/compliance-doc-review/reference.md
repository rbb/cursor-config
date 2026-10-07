# Compliance doc review — codebase anchors

Use these trees when verifying procedures, names, and paths. Prefer
**implementation in repo** over other markdown if they disagree.

## In-repo procedural docs (secondary sources)

| File | Topics |
|------|--------|
| `fntest_install.md` | Pi imaging, DUT firmware, transition bundles |
| `fntest_setup.md` | WCO lab, SSH, MQTT fntest-api, proxies |
| `build-instructions.md` | Builds, `scp_fntest_packages.sh` |
| `verify-locally-opts.md` | Local verify, fntest-loop skills |

## Functional test implementation

| Area | Location |
|------|----------|
| fntest loop Python | `src/judo-radio-utils/testcpu/functional_test/` |
| Recipe / startup cmds | `oe/meta-judo-proprietary/recipes-python/python3-functional-test/files/` |
| fntest container | `oe/meta-judo/meta-judo-ci/recipes-containers/fntest-container/` |
| Deploy helper | `scp_fntest_packages.sh`, `scp_no_flicker_testpi.sh` |

## Compliance / distro

| Area | Location |
|------|----------|
| Compliance feature flag | `build-hs-prod/conf/local.conf`, `build-sumo/conf/local.conf` (`DISTRO_FEATURES` + `compliance`) |
| MQTT fntest API | `MQTT_API_README.md` (`fntest/` topics) |

## Review heuristics

Treat as **check candidates** in the Word doc:

- Shell commands, script paths, host aliases, IP addresses
- Bamboo build paths, bundle filenames, branch names (`enable-compliance`, etc.)
- Package names (`fntest-*`, `python3-*`), systemd units, MQTT topics
- Version thresholds (e.g. builds older than 0.34)
- UI URLs, proxy ports, credential hints (flag doc-only secrets; do not paste into report)

For each claim: **grep** the repo, **read** defining files, note line refs in the report.
