# Снимки интерфейса

Прочитать platform/type SKILL и UI-QUEUE.md. Светлая тема штатным переключателем; проверить actual target и final PNG, не перекрашивать UI через CSS/PNG и не менять цвета фото/видео.

Native75 по умолчанию, browser_zoom.py; проверить реальный zoom и читаемость. Headless shell/mobile могут штатно дать100: раскрыть fallback. При нечитаемом тексте/unsupported native zoom использовать100. CSS zoom/resizing PNG не заменяют native zoom. Одна читаемая capture предпочтительна; длинный блок — сохранённая проверенная platform stitch с overlapping frames, DPR/стыками/границами.

Видеокадр получить внутри duration и подтвердить decoded/paused/nonblack по platform guard; короткие VK видео используют2с либо середину, если2с уже вне длительности. Не выдавать player placeholder за контент. Post/comment/DM/story modes не взаимозаменяемы.

Все source/final pixels просмотреть. JSON success/PNG header/metadata не заменяют visual QA или полноту периода. Preserve browser/user tabs; очистить только own temporaries after receipt, закончить UI before ticket release.
