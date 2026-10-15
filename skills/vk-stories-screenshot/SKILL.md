---
name: vk-stories-screenshot
description: "Снять каждую историю из доступного архивного раздела сообщества VK за явно заданный месяц и год. Не wall-посты, комментарии или DM."
---

# VK stories

Перед запуском проверь [подготовленную среду](../_shared/RUNTIME.md). Компоненты готовит агент после разрешения; сотрудник не устанавливает Python, библиотеки или Node.js и не вводит команды.

Прочитай [SCREENSHOTS](../_shared/SCREENSHOTS.md), [queue](../_shared/UI-QUEUE.md) и [data boundary](../_shared/DATA-BOUNDARY.md). scripts/vk_stories.py — existing implementation, references/vk-ui.example.json historical selector recipe, not a live UI map; actual UI must be verified before capture, no live evidence bundled.

Уточни archive source/month/year/timezone/authority. Полный source inventory/pagination/exhaustion, exact community/story ID/date/author/media до снимка и после. Quiet scroll alone не terminal. Полный список из network/archive и DOM подтверждается отдельно от captured count; manifest unknown не invented total.

Авторизация сотрудника через own manual/native browser flow, explicit private profile либо approved loopback CDP. Профиль хранится вне пакета. Пароль не запрашивается скриптом, не сохраняется в JSON и не читается из файла или переменных среды; команда credentials/--credentials удалена из CLI. Старые файлы пользователя не читать и не удалять автоматически. Never copy an employee session, automatically expire other's ticket or close user's browser. Before manual login release own ticket; nested borrowed caller escalates to parent.

Light UI native75, media RGB unchanged, actual paused story identity/date/media and final PNG checked. Missing avatar exception только explicit owner approval exact full story ID; записать limitation, не общий обход. Unsupported UI/spec/source refusal stops capture; inspect evidence private only. Capture end cleanup/ticket finally; metadata/exit0 не visual/full-period proof.

При первом подключении inspect создаёт private evidence. Рабочий UI map в external state/vk/vk-ui.json требует настоящих observed_at и evidence locators после проверки; не заполнять их фиктивно по публичному recipe. Default map находится вне пакета.

При дефекте/изменении capability выполнять [maintenance](../_shared/MAINTENANCE.md): exact разрешённая роль, sealed incident, candidate и успешный origin replay. Не переносить чужие chat IDs/grants, не считать callback закрытием и не удалять нужные origin assets до получения/приёмки.
