# Внешние зависимости Report Kit

## Текущий состав и границы проверки

Точный состав среды закреплён в assets/runtime-recipe.json выбранного report-kit-agent: Python 3.12.15, Playwright 1.63.0, pyee 13.0.1, greenlet 3.5.6, typing_extensions 4.16.0, Pillow 12.3.0, NumPy 2.3.5, tzdata 2026.5 и дополнительный Node.js 24.21.0 для LiveDune. Агентские исходники и большие архивы среды — разные части поставки. Подготовлены отдельные слои для macOS arm64 и Windows x64; браузер в них не установлен. Сотрудник вручную Python/библиотеки/Node не устанавливает.

Совместная среда и существующие искусственные сценарии проверены на macOS в рамках [проверки dev.25/dev.16](evidence/runtime-checks.json). На Windows проверены только состав и байты архивов, без исполнения. Эти наблюдения не доказывают установку, обновление или работу аккаунтов сотрудника. Требования устройства и получение компонентов — [RUNTIME](skills/_shared/RUNTIME.md).

В runtime assets сохранены 416 файлов LICENSE/NOTICE (212 разных хешей), перечень — assets/runtime-notices.json в пакете агента. Инвентаризация не является полной юридической или независимой проверкой безопасности. До публикации проверить условия распространения CPython, всех wheels, native libraries, Playwright driver, Node/npm и необходимых браузеров; собственная MIT их не заменяет. Подготовка бинарных файлов не снимает это условие.

LiveDune backend остаётся отдельным: frozen npm lock и рецепт есть в этом репозитории, готового node_modules нет. Эффективный минимум Node для его закреплённой цепочки — 20; поставляемый слой содержит 24.21.0. Наличие Node не означает готового backend. Подготовку после разрешения выполняет агент; исходные журналы запросов и ключ не входят в поставку. Условное предупреждение esbuild из Windows-инструкции не объявлено исправленным.

## Исторические инвентаризации 14.10.2026

Всё ниже сохранено в исходных границах: это прежние версии, составы и решения, а не утверждение текущей готовности или отсутствия бинарной поставки. Старые metadata receipts, отказы и ограничения не переписываются. Для текущего решения используйте раздел выше и выбранный recipe.

# Внешние зависимости: проверенные сведения и ограничения

Полный список exact versions, declared license labels, source URLs и hashes JSON-ответов: [REVIEW.json](dependencies/REVIEW.json). Дата проверки14.10.2026. Это инвентаризация первичных метаданных, не legal/security approval исходного кода.

## Покрытие

- Все134 package records и134 snapshots frozen pnpm lock разобраны;208 dependency edges разрешены, отсутствующих/недостижимых snapshots нет. В lock нет license fields.
- Для всех134 exact npm versions получены primary registry metadata; returned name/version и dist integrity совпали с lock. Code/tarballs этих сторонних пакетов не скачивались и не исполнялись. No deprecated label в полученных версиях — не обещание отсутствия vulnerabilities.
- Для четырёх реально установленных Python runtime versions прочитаны installed metadata и exact PyPI metadata: Playwright1.63.0, pyee13.0.1, greenlet3.5.6, typing_extensions4.16.0. Первоначальная отдельная metadata probe typing_extensions4.15.0 не считается установленной версией; её receipt сохранён приватно.
- Provenance двух agent exports и16 source exports:18/18 текущих output hashes совпадают с recorded exports;18/18 read-only donor hashes совпадают с исходным snapshot. Это identity, не доказательство ownership/license.

## Среда запуска

LiveDune backend указывает Node>=18, но обязательная frozen цепочка mcp-openapi0.3.0 → MCP SDK1.32.1 → @hono/node-server2.1.3 требует Node>=20. Перед настройкой/обновлением этой capability проверить реальный исполняемый Node и всю pinned цепочку. Node18 не принимать как совместимый по одному root package. Не запрашивать credentials до проверки среды. Для клиента без LiveDune это не повод установить Node или подключать сервис.

Python root Playwright требует>=3.10; приведённые transitive versions — наблюдение существующей среды, а requirements.txt фиксирует только root. Не заявлять fully frozen reproducible Python install. Resolver/wheel/architecture/Chromium license/build review выполняются на выбранной ОС до согласованной установки; существующие environments не менять по этой инвентаризации.

esbuild0.27.7 declares postinstall. Frozen lock и ignore-scripts не доказывают готовность его platform binary. Не включать lifecycle scripts глобально ради установки: после отдельного разрешения проверить точный разрешённый native runtime path и нужные build steps в изолированной среде. Наличие optional packages для других OS/CPU не означает поддержку всей системой.

## Лицензии и состав поставки

138 exact npm/Python metadata observations содержат MIT(122), ISC(8), BSD-3-Clause(2), BSD-2-Clause(1), Apache-2.0(1), MPL-2.0(1), Python-2.0(1), MIT AND PSF-2.0(1), PSF-2.0(1). Особые записи: @metrichor/jmespath0.3.1 — MPL-2.0; argparse2.0.1 — Python-2.0. Метаданные не заменяют LICENSE/NOTICE каждого поставляемого кода или проверку применимости условий.

Публичные пакеты распространяют generic owner-maintained source, инструкции, lock/recipe и tests. Сторонние node_modules, Python distributions, Chromium/браузерные binaries, установленные plugins, credentials и raw service data не включены. Owner license на свой код не распространяется на downloaded runtimes/сервисы автоматически. При изменении поставки на bundling остановить выпуск и провести отдельную полную license/notice/supply-chain review.

Владелец подтвердил право публикации перенесённого собственного кода и принял MIT. [MIT](LICENSE) добавлена с правообладателем Report Kit; [решение](LICENSE-STATUS.md) относится к собственному коду. Это не разрешение публиковать сейчас. Независимые QA/security и source-code license text review не выполнены этой задачей; accepted клиентские пилоты не заменяют их. Public spec URL LiveDune не является согласованием service/account/data-use условий сотрудника.

## При обновлении

Если package.json/lock/requirements/recipe, platform или binary delivery меняются, пересобрать inventory и повторить exact registry/integrity/engine/notice review. Не считать старые metadata hashes текущими версиями и не скачивать latest вместо pinned package. Raw metadata receipts и вспомогательный fetch script остаются вне Git-пакета. Процесс подготовки парного выпуска находится в report-kit-agent/references/releases.md; при раздельной установке читать выбранную копию этого пакета, не угадывать sibling path.


## Additional source capabilities in dev.5

Instagram/Threads/TikTok reuse existing Playwright1.63.0/Chromium and shared FIFO/zoom; no new browser engine. Telegram/MAX use authorized native computer-use; their common stitch helper requires Pillow and NumPy in a selected external Python runtime. The local image-only fixture ran with Pillow12.3.0/NumPy2.3.5; browser fixtures used the existing Playwright1.63.0 runtime separately. This is not a combined employee environment validation or frozen Python distribution. Pillow/NumPy licensing, transitive/binary/runtime review and target-device checks remain pending. No dependency install or donor authorization import occurred.

## Уточнение состава внешней среды — 14.10.2026

Старая REVIEW.json сохраняет свой snapshot:134 npm и четыре Python distributions. [Дополнительный inventory](dependencies/runtime-review.json) фиксирует ещё две наблюдавшиеся библиотеки: Pillow12.3.0 (MIT-CMU, Python>=3.10) и NumPy2.3.5 (BSD classifier, Python>=3.11). Это точные наблюдения существующей среды, не разрешение установки и не выбор версий сотрудника. Для этого сочетания общий заявленный минимум Python — 3.11; совместимость конкретной ОС, архитектуры и остальных зависимостей проверяется отдельно. Первичные источники: [Pillow12.3.0](https://pypi.org/pypi/Pillow/12.3.0/json), [NumPy2.3.5](https://pypi.org/pypi/numpy/2.3.5/json).

Инвентаризированы пять файлов лицензий существующих distributions, с хешами. У NumPy установленный LICENSE.txt содержит отдельные уведомления компонентов, включая GCC runtime exception и libquadmath; у Pillow установленный текст значительно шире одного названия MIT-CMU. Полная семантическая/юридическая проверка этих текстов не выполнена и требует назначенного независимого проверяющего; материалы сохранены приватно. Название корневой лицензии не заменяет inventory сборки. Если решено поставлять библиотеки/бинарные файлы вместе с продуктом, прежний вывод о составе поставки больше неприменим — нужна новая полная проверка.

В текущем expanded source provenance42 записи, в agent — две: все44 current output hashes проверены. Исторические18/18 относятся к исходному срезу, не ко всем добавленным позже файлам. Это проверка идентичности, не независимый аудит унаследованного кода. Публичная пара поставляет только generic source, инструкции, metadata/recipes/tests; внешние runtime distributions и браузеры не входят в неё.
