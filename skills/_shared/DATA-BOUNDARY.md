# Данные и доступы

Git/plugin содержит инструкции, код, synthetic tests и публичные описания API/селекторов. Не содержит API keys, passwords, cookies, browser profiles, sessions, account emails, client IDs, live screenshots, raw replies или старые клиентские агенты. Имена полей/credential-service и явно синтетические canaries в тестах не реальные credentials.

Private state находится вне package. Setup выбирает папку; общий REPORT_SKILLS_STATE_DIR передаётся всем source skill processes. Default на чистом устройстве: ~/.local/state/report-kit-skills. Не менять env/user config глобально из одного отчёта. Не принимать symlink/чужие профили без review. Фактические permissions проверять на целевой ОС; POSIX modes не доказывают Windows ACL.

Авторизация принадлежит текущему сотруднику/разрешённому аккаунту. Existing source access не разрешает копирование сессии или PII. Secrets вводятся штатным безопасным механизмом, не в чат, CLI argv, Git, receipts или public examples. API adapter не читает secret при list-only; при missing/denied остановка, не поиск другого ключа. PII/raw outputs сохраняются только в private run и передаются внешним сервисам только по принятой data-use policy.

Сначала клиент/период/source authority, потом доступ. UI screenshots могут содержать персональные данные: аудитория итогового файла/маскирование определяются владельцем до sharing. Скрипт не выдаёт права самостоятельно. Техническое присутствие папки/очереди не enforced isolation.

Cleanup: сохранить exact path/hash/result receipt перед удалением известных task temporaries. Не удалять originals/finals/accepted histories/needed recovery evidence или чужую папку целиком. Auth/state не временный PNG; удаление/отзыв отдельно согласовать с владельцем. No source/package writes during report work.
