---
name: vk-comment-screenshot
description: "Снять только комментарии и вложенные ответы к конкретному посту VK по wall-ссылке. Не сам пост, истории или личные сообщения."
---

# VK comments

Прочитай [SCREENSHOTS](../_shared/SCREENSHOTS.md), [queue](../_shared/UI-QUEUE.md) и [data boundary](../_shared/DATA-BOUNDARY.md). scripts/vk_comment_screenshoter.py импортирует sibling vk-post-screenshot/scripts; оба обязательны. Не отправлять задачу в message/post maintainer по сходству названия.

Снять только загруженную ветку exact post/reply со всеми requested visible nested replies. SPA target wall_comments_layout_root; исключить форму/кнопки загрузки, но не общий контейнер, содержащий сами комментарии. Пустой список — failure, не blank PNG. Loaded visible subset не доказательство всех комментариев сервера.

Output private external run, light target/final PNG, native75/readable100 и own UI ticket. Автор/дата/text/ответ не обрезаны, чужой соседний post исключён. Сохранить source/reply locator и coverage; не выдумывать полную moderation месячную выборку из одного снимка. Credentials и recovery только как у post skill.

При дефекте/изменении capability выполнять [maintenance](../_shared/MAINTENANCE.md): exact разрешённая роль, sealed incident, candidate и успешный origin replay. Не переносить чужие chat IDs/grants, не считать callback закрытием и не удалять нужные origin assets до получения/приёмки.
