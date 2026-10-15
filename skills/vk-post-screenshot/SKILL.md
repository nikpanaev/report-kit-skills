---
name: vk-post-screenshot
description: "Снять конкретные публикации VK по wall-ссылкам: полный пост или его реальные материалы. Не снимки только комментариев, историй или переписки."
---

# VK posts

Перед запуском проверь [подготовленную среду](../_shared/RUNTIME.md). Компоненты готовит агент после разрешения; сотрудник не устанавливает Python, библиотеки или Node.js и не вводит команды.

Прочитай [SCREENSHOTS](../_shared/SCREENSHOTS.md), [queue](../_shared/UI-QUEUE.md) и [data boundary](../_shared/DATA-BOUNDARY.md). Используй scripts/vk_post_screenshoter.py и pinned Playwright dependency, не новую реализацию. Output только в private run вне пакета.

Validate exact wall URL/post ID. По умолчанию full text; collapsed/visual-only/all-visuals только по задаче. All materials из настоящих attachment roots, не avatar/emoji/linkpreview/comments; проверить expected/obtained/order/identity. Comments separately own skill.

Авторизация сотрудника: manual login либо разрешённый loopback CDP; не экспортировать чужие cookies. Default session external state, никогда Git. CDP creates/closes only own tab, no browser/context close. Неподдержанный endpoint/login combination отвергается. No global browser settings overwrite.

Светлая тема target/final PNG и native75/100 fallback проверяются штатно. VK video guards: decoded, paused, inside duration, nonblack; short duration≤3 uses2s, ≤2 midpoint. SPA/legacy attachments проверяются одинаково. Ошибка/429 stops, no rate-limit retries or fake success. Полный текст/last rows/materials и source-to-PNG proof проверить visually.

При missing dependency/access/theme прекратить dependent capture, выполнить предусмотренный manual handoff после освобождения own ticket. Existing borrowed ticket belongs to parent. Не обходить отказ другим capture engine; actual target-device behaviour ещё не подтверждено этим пакетом.

При дефекте/изменении capability выполнять [maintenance](../_shared/MAINTENANCE.md): exact разрешённая роль, sealed incident, candidate и успешный origin replay. Не переносить чужие chat IDs/grants, не считать callback закрытием и не удалять нужные origin assets до получения/приёмки.
