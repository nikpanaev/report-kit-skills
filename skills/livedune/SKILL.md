---
name: livedune
description: "Получить статистику LiveDune, штатные выгрузки и снимки его интерфейса для заданных источников/периода. Не создавать публикации и не изменять клиентские источники."
---

# LiveDune

Перед запуском проверь [подготовленную среду](../_shared/RUNTIME.md). Компоненты готовит агент после разрешения; сотрудник не устанавливает Python, библиотеки или Node.js и не вводит команды.

Прочитай [data boundary](../_shared/DATA-BOUNDARY.md) и [API](references/API.md) для запросов; [metrics](references/METRICS.md) для расчётов. Источник/period/timezone/network/account и approved budget подтвердить перед collection. Сначала внутренний браузер, если доступен; UI screenshot — [SCREENSHOTS](../_shared/SCREENSHOTS.md) и единая [queue](../_shared/UI-QUEUE.md). Native exports не скриншоты UI.

API: только ready backend mcp-openapi0.3.0 через scripts/mcp-run.mjs, exact spec hash, GET allowlist, no redirects/retries, cap1–200 и append-only STARTED ledger. Список tools без Keychain/HTTP. Actual credentials не являются package input; macOS использует прежний Keychain. Для Windows подготовлен отдельный адаптер Credential Manager/приватных папок, настоящая проверка выполняется пользователем по [Windows](references/WINDOWS.md); статус USER_CHECK_REQUIRED до её результата. Иные ОС не поддерживаются этим API CLI. Не принимать token от модели и не печатать raw errors/key.

Все cursors до окончания; raw replies/private hashes до preview/расчётов. HTTP/provider/schema/timeout/uncertain failures ненулевой exit; no blind retry/new run-dir bypass. Provider restriction/access error не0. Budget учитывает STARTED и сохраняется при restart; изменять только по отдельному разрешению внутри max200.

Исторический принятый snapshot переиспользовать без новых запросов при соответствующем клиентском contract. Свежие счётчики не подгонять. Full coverage/identity/dates/formulas отдельно от transport exit0. Указать missing source и ограничения; не утверждать actual account/API readiness по offline tests.

При дефекте/изменении capability выполнять [maintenance](../_shared/MAINTENANCE.md): exact разрешённая роль, sealed incident, candidate и успешный origin replay. Не переносить чужие chat IDs/grants, не считать callback закрытием и не удалять нужные origin assets до получения/приёмки.
