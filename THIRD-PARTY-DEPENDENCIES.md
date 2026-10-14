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

Владелец подтвердил право публикации перенесённого собственного кода и принял MIT. В LICENSE-STATUS остаётся согласование публичного имени правообладателя и текста LICENSE. Это не разрешение публиковать сейчас. Независимые QA/security и source-code license text review не выполнены этой задачей; accepted клиентские пилоты не заменяют их. Public spec URL LiveDune не является согласованием service/account/data-use условий сотрудника.

## При обновлении

Если package.json/lock/requirements/recipe, platform или binary delivery меняются, пересобрать inventory и повторить exact registry/integrity/engine/notice review. Не считать старые metadata hashes текущими версиями и не скачивать latest вместо pinned package. Raw metadata receipts и вспомогательный fetch script остаются вне Git-пакета. Процесс подготовки парного выпуска находится в report-kit-agent/references/releases.md; при раздельной установке читать выбранную копию этого пакета, не угадывать sibling path.


## Additional source capabilities in dev.5

Instagram/Threads/TikTok reuse existing Playwright1.63.0/Chromium and shared FIFO/zoom; no new browser engine. Telegram/MAX use authorized native computer-use; their common stitch helper requires Pillow and NumPy in a selected external Python runtime. The local image-only fixture ran with Pillow12.3.0/NumPy2.3.5; browser fixtures used the existing Playwright1.63.0 runtime separately. This is not a combined employee environment validation or frozen Python distribution. Pillow/NumPy licensing, transitive/binary/runtime review and target-device checks remain pending. No dependency install or donor authorization import occurred.
