---
name: vk-message-screenshot
description: "Снять доступные администратору переписки сообщества VK за заданные полные даты/месяц. Не комментарии к постам или клиппинг публикаций."
---

# VK messages

Перед запуском проверь [подготовленную среду](../_shared/RUNTIME.md). Компоненты готовит агент после разрешения; сотрудник не устанавливает Python, библиотеки или Node.js и не вводит команды.

Прочитай [SCREENSHOTS](../_shared/SCREENSHOTS.md), [queue](../_shared/UI-QUEUE.md) и [data boundary](../_shared/DATA-BOUNDARY.md). scripts/vk_messages.py использует sibling vk-stories-screenshot/scripts/vk_stories.py для session/auth; dependency required, no copied sessions. Output private external run.

Уточни community source/access, explicit peers или all, year/date range/timezone. list-only даёт candidates, не capture/полный месяц. Право читать DM должно быть подтверждено; display-name не identity. Не отправлять сообщения или менять переписку.

Loopback CDP либо разрешённый personal profile с channel; пароль не сохранять и не читать из JSON/переменных среды; manual recovery сохраняет разрешённую сессию. Старые файлы паролей автоматически не читать и не удалять. Admin inbox href validate before navigate; actual access/list completeness/response history confirm. Сохранять request/response observer identity/count/chronology и own staged screenshots до повторной валидации диалога. Quiet scroll не полнота.

Если только observed DOM без server ID/period exhaustion, manifest complete=false и limitation; читаемый частичный PNG не full month success. Все required cases и ответы по профилю, light pixels/native zoom/long-message stitch проверяются. Полные screenshots may contain PII, recipient policy before sharing. Нет обхода denial или самостоятельной альтернативной съёмки.

При дефекте/изменении capability выполнять [maintenance](../_shared/MAINTENANCE.md): exact разрешённая роль, sealed incident, candidate и успешный origin replay. Не переносить чужие chat IDs/grants, не считать callback закрытием и не удалять нужные origin assets до получения/приёмки.
