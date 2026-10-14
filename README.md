# report-skills

Локальная подготовка переносимого комплекта для будущих отчётов. Версия: [VERSION](VERSION). Maturity: prototype; channel: development; stable release отсутствует.

Публикация, установка и подключение аккаунтов не разрешены этим этапом. Существующие клиентские агенты и материалы не включены. Git remote: no remote. Лицензия распространения пока не выбрана владельцем.

## Начальный набор

Пять source skills: LiveDune, VK posts, comments, messages, stories. [Каталог](capabilities.json) фиксирует required transitive skills и NOT_INCLUDED для остальных площадок. Comments reuse posts; messages reuse stories. Общие очередь/zoom/private path guard — skills/_shared, не отдельный capture engine.

[Scope/платформенные ограничения](CHANGE-SPEC.md), [provenance](SOURCE-PROVENANCE.json), [проверки](EVIDENCE-INDEX.md). Наличие SKILL.md не доказывает installation/invocation/live readiness. Employee data находится вне package: REPORT_SKILLS_STATE_DIR; каждый task output в его private run. Явные in-package data paths отвергаются.

OpenAPI сохраняется как source/hash в dependencies/livedune/recipe.json; schema и готовый backend не vendored. Сохранён frozen npm lock; установка разрешается отдельно, во внешнем runtime. CLI Keychain adapter macOS only, Windows/другой runtime не подтверждены. Playwright1.63.0/Chromium и Codeх-connected tooling также требуют выбора и проверки, без включения binaries/session.

Public historical VK UI recipe не live evidence. Working observed map private; default CLI требует его после actual observation, см. skills/vk-stories-screenshot/references/ui.md. Не добавлять фиктивные evidence locators ради PASS.

Локальные тесты: `python3 scripts/test_runtime_paths.py`, `node scripts/test_runtime_paths.mjs`, `node skills/livedune/scripts/check.mjs`. Полные VK/zoom fixture checks требуют заранее разрешённого Playwright1.63.0/browser runtime; такие checks могут использовать task-owned окна только synthetic fixture, не user session. Общий read-only package checker хранится в report-agent/scripts/check_package.py и может проверять этот репозиторий без исполнения его файлов.

Никаких keys/session/profile/account/client data в public files/Git. License и independent review pending. Known cold rate-limit fixture failure сохранён в evidence и не скрыт isolated pass.

## Product Versioning + Maturity/Channel Contract

- **Maturity phase:** prototype
- **Release channel:** development
- **Public compatibility promise:** none; no employee-device/account/runtime support validated yet
- **1.0.0 entry criteria:** actual supported-device/account install and control report; reviewed license/dependencies; independent QA/security; packaged acceptance and separate owner G6
- **Rebaseline policy:** only explicit owner decision before external distribution; never rename old artifacts or silently migrate private workspaces
- **Release destination:** local-only
- **External AI/model API:** not applicable; no new model API client or SDK/key provisioning; employee Codex provider/data-use terms must be checked before live work

VERSION is the sole development-version source; plugin manifest is a checked mirror. Package content identity and private workspace schema are separate. Public GitHub release/URLs require later explicit authority.
