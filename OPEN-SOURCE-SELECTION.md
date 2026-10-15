# Source capability selection — offline preparation

| Capability | Source / exact identity | License / distribution | Decision |
|---|---|---|---|
| LiveDune transport | Ready mcp-openapi0.3.0, original spec1.0.10 hash in recipe | Backend declares MIT in actual installed metadata; binary/node_modules not shipped; transitive license review pending | Reuse; preserve GET guard/raw archive/cap, no own HTTP client |
| Browser automation | Existing Playwright1.63.0 | Actual installed Playwright1.63.0 metadata: Apache-2.0, Python>=3.10; runtime prepared as separate agent release assets, browser not installed; complete distribution notices review pending | Reuse approved version, no new engine |
| Source capture/session/zoom/FIFO | Owner-maintained exported code, SOURCE-PROVENANCE.json | Own-code MIT selected, copyright Report Kit; third-party review pending; no historical private evidence/author metadata | Adapt only portable paths/privacy and synthetic fixtures |
| Persistence/path validation | Python SQLite/pathlib and Node fs/path | Standard library, no third-party dependency added | One external private store; scoped local checks |
| Secret storage | macOS Keychain; Windows native Credential Manager via built-in Windows PowerShell5.1/.NET | No new library/key/cookie/session shipped; Windows native verification assigned to user | Preserve macOS route; Windows candidate only, fail closed on access/policy/ACL failure |
| Installation/update | Native host plugin mechanism | No hook/server/global config changes in this slice | Prepare source manifests; actual device install deferred |

Canonical references: https://registry.npmjs.org/mcp-openapi/0.3.0 ; https://github.com/Docat0209/mcp-openapi ; https://api.livedune.com/docs/openapi.json . Recipe and lock provide identities, not permission to download or execute. Source cache is not a new verified installation.

The agent package now prepares a separate pinned portable runtime and native inert bootstrap; no second installer daemon or new API transport is added. Missing/unverified components stop the affected source step. Complete license/supply-chain review and independent security remain release requirements; binaries are separate release assets, not source Git files.

## Historical dependency observation — 14 October 2026

[Metadata inventory](dependencies/REVIEW.json) covers134 npm exact versions and four observed Python distributions. [Findings/limits](THIRD-PARTY-DEPENDENCIES.md): effective Node>=20 for frozen LiveDune chain; Python transitive resolver not frozen; esbuild postinstall needs approved runtime validation. Source origins18/18 across the two packages match their recorded hashes. These results do not close ownership/license/security/host acceptance. No dependency installed, version changed or third-party code vendored.

## Windows credential preparation

Owner assigned Windows runtime verification to the user. Reuse native WinCred/DirectorySecurity rather than installing a secret-store package or creating encryption. A narrow local wrapper retrieves only the selected credential through a captured pipe and creates/checks private directories; no installer, environment-token fallback, policy changes, service or HTTP client. Other programs of the same OS user/admin are outside the isolation claim. Actual Windows/Powershell/ACL/browser checks remain USER_CHECK_REQUIRED.

## Обезличенные сведения для поддержки

Использовать стандартные json/uuid/zipfile/fs/crypto и existing diagnostic transitions. Не вводить telemetry SDK, отдельный API journal или remote sender. Один Python collector и policy зеркалируются agent package для независимого offline fallback; Node имеет только writer по той же policy. Подтверждение privacy требует проверок реального архива, а не слова sanitized у прежних raw logs.

## Переносимая среда — принято 15.10.2026

Используется готовая CPython3.12.15 python-build-standalone20261013, exact wheels и официальный Node24.21.0. Recipe/платформенные assets сопровождаются report-kit-agent; нового package manager/daemon/второго установщика нет. Для первой подготовки без Python — нативные shell/PowerShell helper, только проверенная inert распаковка. Зависимости собираются без pip/lifecycle execution, internal vendor links нормализуются в обычные файлы и проходят прежнюю archive path/collision проверку. Source archives по умолчанию остаются strict UTF-8; отдельный binary mode только для проверенного runtime. Native browser installation оставлена штатному Playwright после отдельного согласия. Полный license/NOTICE inventory в agent/assets/runtime-notices.json и самих runtime assets; независимое решение о распространении не подменяется сборкой.

## Выбор упрощения среды — 15.10.2026

Границы: точная склейка кадров прокрутки без геометрического искажения/перерисовки, Windows11+x64/macOS14+arm64, без ручной установки сотрудником. Новые программы не устанавливались. До сравнения заданы пиксельная эквивалентность/те же отказы, время<=2x baseline и память<=baseline+20MiB.

| Готовое решение | Источник, версия и условия | Решение |
|---|---|---|
| Pillow | Уже включённая12.3.0; [официальная лицензия MIT-CMU](https://github.com/python-pillow/Pillow/blob/12.3.0/LICENSE), [ImageChops](https://pillow.readthedocs.io/en/stable/reference/ImageChops.html), [ImageStat](https://pillow.readthedocs.io/en/stable/reference/ImageStat.html). Native libraries сохраняют свои тексты из точного wheel. | Использовать существующие операции difference/mean/stddev; заменить только вычисления прежнего stitcher, сохранить его интерфейс и пороги. Результаты — evidence/pillow-runtime-checks.json. |
| OpenCV Python | [4.12.0.88, первичные метаданные PyPI](https://pypi.org/pypi/opencv-python/4.12.0.88/json); Apache2.0 с отдельными bundled notices. Для Python>=3.9 требует NumPy>=2,<2.3. | Отклонить: не устраняет NumPy, добавляет native package и меняет его версию. Полный panorama pipeline для точной склейки не требуется. Установка/полный security-аудит отклонённого кандидата не выполнялись. |
| uv | [Официальное описание управляемого Python](https://docs.astral.sh/uv/concepts/python-versions/). CPython получает из Astral python-build-standalone, как текущий рецепт. Исполняемая версия uv не выбиралась и не скачивалась. | Не добавлять второй package manager ради тех же binaries: вопрос Microsoft он не решает. Вернуться к выбору при реальном недостатке текущего native bootstrap. |
| CPython/Astral | Существующая3.12.15, python-build-standalone20261013; exact size/hash/URL в recipe агента. Python и встроенные компоненты сохраняют собственные лицензии. | Сохранить готовую среду и единый путь обновлений; не менять всю поставку на сборку у сотрудника ради неподтверждённого общего запрета. Windows-условия — LICENSE-STATUS.md. |

Новая внешняя библиотека, installer, HTTP-клиент или сервис не добавлены. Минимальное собственное изменение — вызовы уже выбранного Pillow в существующем stitcher. Контроль качества: исходные bytes и joins/отказы против неизменённого dev.19, тест без NumPy, размер/состав архива; память и время измеряются отдельно. Изменение требований к изображениям или провал этих проверок возвращает выбор на пересмотр. Независимая безопасность/юридическое решение о выпуске не подменяются этим выбором.
